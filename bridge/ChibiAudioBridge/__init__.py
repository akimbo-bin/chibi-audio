from __future__ import absolute_import, print_function

from .bridge import AbletonLiveMCP
from .chibitap_multi import install_chibitap_multi_instance


install_chibitap_multi_instance(AbletonLiveMCP)


def create_instance(c_instance):
    return AbletonLiveMCP(c_instance)
