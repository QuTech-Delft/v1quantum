"""Definitions of the message types used by the control plane."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

from v1quantum.processor import BsmGroupEntry


class QcpOp(Enum):
    """Message types."""
    OP_PING = 0x00
    OP_RSRV = 0x01
    OP_FREE = 0x02
    OP_RULE = 0x03


@dataclass
class QcpMsg:
    """Base information for all messages."""
    msg_type: QcpOp


@dataclass
class RequestMsg(QcpMsg):
    """Make a new request to the controller."""
    source: str
    remote: str
    request_id: int


class RuleAction(Enum):
    """Possible rule actions."""
    INSERT_TABLE_ENTRY = 0x00
    REMOVE_TABLE_ENTRY = 0x01
    CREATE_BSM_GRP = 0x02
    DESTROY_BSM_GRP = 0x03


@dataclass
class RuleMsg(QcpMsg):
    """Base information for rule messages."""
    circuit_id: int
    node: str
    rule_id: int
    rule_action: RuleAction


@dataclass
class TableInsertMsg(RuleMsg):
    """Insert a table entry."""
    block: str
    table: str
    key: List
    action_name: str
    action_data: List
    handle: Optional[int] = None


@dataclass
class TableRemoveMsg(RuleMsg):
    """Remove a table entry."""
    block: str
    table: str
    handle: int


@dataclass
class BsmGrpCreateMsg(RuleMsg):
    """Create a BSM group."""
    bsm_grp_id: int
    bsm_grp_entry_0: BsmGroupEntry
    bsm_grp_entry_1: BsmGroupEntry


@dataclass
class BsmGrpDestroyMsg(RuleMsg):
    """Destroy a BSM group."""
    bsm_grp_id: int
