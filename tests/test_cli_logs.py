import logging

from fleet.cli import quiet_library_logs


def test_library_logs_are_off_in_runs_and_back_on_request():
    try:
        quiet_library_logs({})
        assert not logging.getLogger("ats_scrapers.paylocity").isEnabledFor(logging.ERROR)
        logging.disable(logging.NOTSET)
        quiet_library_logs({"FLEET_VERBOSE_LOGS": "1"})
        assert logging.getLogger("ats_scrapers.paylocity").isEnabledFor(logging.WARNING)
    finally:
        logging.disable(logging.NOTSET)
