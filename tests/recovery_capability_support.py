"""Explicit scripted boundary for the pinned Hermes custom-toolset API.

This is test data, not an SDK or model qualification. The actual SDK separately
resolves its schemas; these fixtures declare the same read/write-only contract.
"""
from copy import deepcopy
from types import ModuleType


def definitions(names=('read_file', 'write_file')):
    return [{'type': 'function', 'function': {'name': name,
            'parameters': {'type': 'object', 'properties': {}}}} for name in names]


class ReadWriteToolsets(ModuleType):
    def __init__(self):
        super().__init__('toolsets')
        self.registrations = []

    def create_custom_toolset(self, name, description, tools=None, includes=None):
        assert name == 'adaptive_file_read_write', name
        assert isinstance(description, str) and description
        assert tools == ['read_file', 'write_file'], tools
        assert includes == [], includes
        self.registrations.append((name, description, deepcopy(tools), deepcopy(includes)))

    def agent_tools(self, enabled_toolsets):
        assert enabled_toolsets == ['adaptive_file_read_write'], enabled_toolsets
        assert len(self.registrations) == 1, self.registrations
        return definitions(), {'read_file', 'write_file'}
