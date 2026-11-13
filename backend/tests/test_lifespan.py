"""
Foja AI — Phase 2.4.6.1.1: Application Lifespan Cleanup Regression Tests.

Verifies:
1. Successful startup and shutdown order.
2. Database initialization failure handling (disposal still attempted, original exception propagated).
3. Extraction shutdown failure handling (database disposal still attempted, exception propagated).
4. Repeated startup and shutdown cycles in the same process.
5. Task scheduling after a valid restart (task manager reset).
6. Database disposal attempted even when another cleanup operation fails.
7. Application runtime exception propagation with guaranteed cleanup.

Strict safety requirements:
- Fully isolated in-memory testing using mocks.
- Never touches data/foja.db or production records.
"""

import sys
from pathlib import Path

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.main import app, lifespan
from app.services.memory.extraction import (
    MemoryExtractionTaskManager,
    extraction_task_manager,
)


class TestApplicationLifespanCleanup(unittest.IsolatedAsyncioTestCase):
    """
    Regression test suite for guaranteed application lifespan cleanup and shutdown ordering.
    """

    def setUp(self):
        extraction_task_manager.reset_for_tests()

    def tearDown(self):
        extraction_task_manager.reset_for_tests()

    # --------------------------------------------------------------------------
    # 1. Successful startup and shutdown with strict execution order
    # --------------------------------------------------------------------------
    async def test_lifespan_successful_startup_and_shutdown_order(self):
        """
        Verify startup and shutdown execute in the strictly required sequence:
        Startup:
          1. startup_extraction_tasks
          2. init_db
        Shutdown:
          3. shutdown_extraction_tasks (stop accepting, wait active, cancel if timed out)
          4. close_db (dispose database engine)
        """
        call_order = []

        def mock_startup():
            call_order.append("startup_extraction_tasks")

        async def mock_init_db():
            call_order.append("init_db")

        async def mock_shutdown_tasks(timeout=None):
            call_order.append("shutdown_extraction_tasks")
            return {"completed": 0, "cancelled": 0, "timed_out": 0}

        async def mock_close_db():
            call_order.append("close_db")

        with patch("app.main.startup_extraction_tasks", side_effect=mock_startup), \
             patch("app.main.init_db", side_effect=mock_init_db), \
             patch("app.main.shutdown_extraction_tasks", side_effect=mock_shutdown_tasks), \
             patch("app.main.close_db", side_effect=mock_close_db):

            async with lifespan(app):
                call_order.append("app_running")

        expected_order = [
            "startup_extraction_tasks",
            "init_db",
            "app_running",
            "shutdown_extraction_tasks",
            "close_db",
        ]
        self.assertEqual(call_order, expected_order)

    # --------------------------------------------------------------------------
    # 2. Database initialization failure handling
    # --------------------------------------------------------------------------
    async def test_lifespan_database_initialization_failure_guarantees_cleanup(self):
        """
        Verify that if init_db fails on startup:
        - close_db() is still called to dispose of any partial connection pool.
        - shutdown_extraction_tasks() is called.
        - The original startup exception is propagated (NOT silently swallowed).
        """
        db_disposed = False
        tasks_shut_down = False

        async def failing_init_db():
            raise RuntimeError("Database connection timed out or schema init failed.")

        async def mock_close_db():
            nonlocal db_disposed
            db_disposed = True

        async def mock_shutdown_tasks(timeout=None):
            nonlocal tasks_shut_down
            tasks_shut_down = True
            return {"completed": 0, "cancelled": 0, "timed_out": 0}

        with patch("app.main.init_db", side_effect=failing_init_db), \
             patch("app.main.close_db", side_effect=mock_close_db), \
             patch("app.main.shutdown_extraction_tasks", side_effect=mock_shutdown_tasks):

            with self.assertRaises(RuntimeError) as ctx:
                async with lifespan(app):
                    pass

            # Original startup exception must be preserved
            self.assertIn("Database connection timed out or schema init failed.", str(ctx.exception))

            # Database disposal and task draining must have been attempted
            self.assertTrue(db_disposed, "close_db() was not called when init_db failed!")
            self.assertTrue(tasks_shut_down, "shutdown_extraction_tasks() was not called when init_db failed!")

    # --------------------------------------------------------------------------
    # 3. Extraction shutdown failure handling
    # --------------------------------------------------------------------------
    async def test_lifespan_extraction_shutdown_failure_guarantees_db_disposal(self):
        """
        Verify that if shutdown_extraction_tasks raises an exception:
        - close_db() is STILL called to dispose of the database engine.
        - The shutdown exception is propagated (NOT silently swallowed).
        """
        db_disposed = False

        async def mock_init_db():
            pass

        async def failing_shutdown_tasks(timeout=None):
            raise TimeoutError("Extraction tasks failed to drain within timeout.")

        async def mock_close_db():
            nonlocal db_disposed
            db_disposed = True

        with patch("app.main.init_db", side_effect=mock_init_db), \
             patch("app.main.shutdown_extraction_tasks", side_effect=failing_shutdown_tasks), \
             patch("app.main.close_db", side_effect=mock_close_db):

            with self.assertRaises(TimeoutError) as ctx:
                async with lifespan(app):
                    pass

            self.assertIn("Extraction tasks failed to drain", str(ctx.exception))
            self.assertTrue(db_disposed, "close_db() was not called when extraction shutdown raised an exception!")

    # --------------------------------------------------------------------------
    # 4. Repeated startup and shutdown in the same process
    # --------------------------------------------------------------------------
    async def test_lifespan_repeated_cycles_in_same_process(self):
        """
        Verify the application can start up and shut down repeatedly without
        accumulating broken state or stale shutdown flags.
        """
        init_count = 0
        close_count = 0

        async def mock_init_db():
            nonlocal init_count
            init_count += 1

        async def mock_close_db():
            nonlocal close_count
            close_count += 1

        with patch("app.main.init_db", side_effect=mock_init_db), \
             patch("app.main.close_db", side_effect=mock_close_db):

            # Cycle 1
            async with lifespan(app):
                self.assertFalse(extraction_task_manager.is_shutting_down)
            self.assertTrue(extraction_task_manager.is_shutting_down)

            # Cycle 2
            async with lifespan(app):
                self.assertFalse(extraction_task_manager.is_shutting_down)
            self.assertTrue(extraction_task_manager.is_shutting_down)

            # Cycle 3
            async with lifespan(app):
                self.assertFalse(extraction_task_manager.is_shutting_down)
            self.assertTrue(extraction_task_manager.is_shutting_down)

        self.assertEqual(init_count, 3)
        self.assertEqual(close_count, 3)

    # --------------------------------------------------------------------------
    # 5. Task scheduling after a valid restart
    # --------------------------------------------------------------------------
    async def test_task_scheduling_after_valid_restart(self):
        """
        Verify that after shutting down, starting a new lifespan cycle re-enables
        task scheduling and successfully registers active tasks.
        """
        async def mock_init_db():
            pass

        async def mock_close_db():
            pass

        with patch("app.main.init_db", side_effect=mock_init_db), \
             patch("app.main.close_db", side_effect=mock_close_db):

            # Initial run
            async with lifespan(app):
                pass
            # At this point, task manager was shut down
            self.assertTrue(extraction_task_manager.is_shutting_down)

            # Re-start application lifespan
            async with lifespan(app):
                self.assertFalse(extraction_task_manager.is_shutting_down)

                with patch.object(settings, "MEMORY_EXTRACTION_ENABLED", True):
                    async def dummy_coro(*args, **kwargs):
                        await asyncio.sleep(0.01)
                        return []

                    with patch("app.services.memory.extraction.run_memory_extraction_task", side_effect=dummy_coro):
                        task = extraction_task_manager.schedule("conv_restarted_1", "default_user")
                        self.assertIsNotNone(task, "Task was unexpectedly rejected after restart!")
                        self.assertIn("conv_restarted_1", extraction_task_manager.get_active_tasks())
                        await task

    # --------------------------------------------------------------------------
    # 6. Database disposal attempted even when another cleanup operation fails
    # --------------------------------------------------------------------------
    async def test_database_disposal_attempted_when_another_cleanup_fails(self):
        """
        Verify that close_db is called even if shutdown_extraction_tasks raises
        an arbitrary unhandled exception.
        """
        mock_close = AsyncMock()
        mock_shutdown = AsyncMock(side_effect=ValueError("Unexpected crash in task drain logic"))

        with patch("app.main.init_db", new_callable=AsyncMock), \
             patch("app.main.shutdown_extraction_tasks", mock_shutdown), \
             patch("app.main.close_db", mock_close):

            with self.assertRaises(ValueError):
                async with lifespan(app):
                    pass

            mock_close.assert_awaited_once()

    # --------------------------------------------------------------------------
    # 7. Application execution crash preserves exception while executing cleanup
    # --------------------------------------------------------------------------
    async def test_lifespan_preserves_runtime_crash_with_full_cleanup(self):
        """
        Verify that if the application crashes during execution (inside yield):
        - Both shutdown_extraction_tasks and close_db are executed.
        - The original runtime exception is preserved and propagated.
        """
        cleanup_order = []

        async def mock_shutdown(timeout=None):
            cleanup_order.append("shutdown")
            return {"completed": 0, "cancelled": 0, "timed_out": 0}

        async def mock_close():
            cleanup_order.append("close_db")

        with patch("app.main.init_db", new_callable=AsyncMock), \
             patch("app.main.shutdown_extraction_tasks", side_effect=mock_shutdown), \
             patch("app.main.close_db", side_effect=mock_close):

            with self.assertRaises(ZeroDivisionError):
                async with lifespan(app):
                    raise ZeroDivisionError("Simulated server crash during request handling")

            self.assertEqual(cleanup_order, ["shutdown", "close_db"])


if __name__ == "__main__":
    unittest.main()
