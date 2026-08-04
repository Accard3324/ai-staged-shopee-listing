from __future__ import annotations

from typing import List

from ..ziniao_connector import CdpCandidate, discover_cdp_candidates, parse_cdp_processes


def find_ziniao_cdp_candidates(verify: bool = True) -> List[CdpCandidate]:
    return discover_cdp_candidates(verify=verify)
