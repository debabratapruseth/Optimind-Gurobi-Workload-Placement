"""Pytest reporting plugin used only by runtime verification; never loads models."""
from .persistence import json_write


def pytest_addoption(parser):
    parser.addoption('--runtime-test-report', default=None)


def pytest_configure(config):
    global evidence, outcomes
    evidence = dict(collected=0, nodeids=[], failed_tests=[], collection_errors=[], warnings=[])
    outcomes = {}


def pytest_collection_finish(session):
    evidence['nodeids'] = sorted(item.nodeid for item in session.items)
    evidence['collected'] = len(session.items)


def pytest_collectreport(report):
    if report.failed:
        evidence['collection_errors'].append(dict(nodeid=report.nodeid, reason=str(report.longrepr)))


def pytest_runtest_logreport(report):
    if report.failed:
        outcomes[report.nodeid] = 'failed'
        evidence['failed_tests'].append(dict(nodeid=report.nodeid, phase=report.when, reason=str(report.longrepr)))
    elif report.skipped and outcomes.get(report.nodeid) != 'failed':
        outcomes[report.nodeid] = 'skipped'
    elif report.when == 'call' and outcomes.get(report.nodeid) not in ('failed', 'skipped'):
        outcomes[report.nodeid] = 'passed'


def pytest_warning_recorded(warning_message, when, nodeid, location):
    evidence['warnings'].append(dict(nodeid=nodeid, reason=str(warning_message.message)))


def pytest_sessionfinish(session, exitstatus):
    evidence.update(exit_code=int(exitstatus), **{key: sum(v == key for v in outcomes.values()) for key in ('passed', 'failed', 'skipped')})
    path = session.config.getoption('--runtime-test-report')
    if path:
        json_write(path, evidence)
