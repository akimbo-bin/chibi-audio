from __future__ import absolute_import, print_function

from . import bridge as _bridge
from .bounded_control import BOUNDED_CONTROL_METHODS, install_bounded_control
from .chibitap_multi import install_chibitap_multi_instance
from .locator_read import LOCATOR_READ_METHODS, install_locator_read


AbletonLiveMCP = _bridge.AbletonLiveMCP
install_chibitap_multi_instance(AbletonLiveMCP)
install_bounded_control(AbletonLiveMCP)
install_locator_read(AbletonLiveMCP)

_bridge.MODEL_READ_METHODS = _bridge.MODEL_READ_METHODS + LOCATOR_READ_METHODS

# Register only reviewed methods with the existing bridge policy. This keeps the
# core bridge and ChibiTap lane independent while preserving fail-closed dispatch.
_bridge.MODEL_BOUNDED_WRITE_METHODS = (
    _bridge.MODEL_BOUNDED_WRITE_METHODS + BOUNDED_CONTROL_METHODS
)
_bridge.MODEL_EXPOSED_METHODS = (
    _bridge.MODEL_READ_METHODS
    + _bridge.MODEL_BOUNDED_WRITE_METHODS
    + _bridge.MODEL_CAPTURE_METHODS
)


def create_instance(c_instance):
    return AbletonLiveMCP(c_instance)
