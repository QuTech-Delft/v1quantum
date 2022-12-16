"""The Agent protocol."""

from typing import Callable, Dict

from netsquid.protocols.nodeprotocols import NodeProtocol
from pyp4.table import Table

from v1quantum.protocol.control_plane.protocol import (
    BsmGrpCreateMsg,
    BsmGrpDestroyMsg,
    QcpMsg,
    QcpOp,
    RuleAction,
    RuleMsg,
    TableInsertMsg,
    TableRemoveMsg,
)


CTL_PORT = 0x200


class Agent(NodeProtocol):
    """The Agent protocol.

    The agent protocol installs rules into the data plane as instructed by the central controller.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The node on which this protocol is running.

    """

    def __init__(self, node, config, **kwargs):
        # pylint: disable=unused-argument
        super().__init__(node, f"{node.name}-agent")
        self.__dispatch: Dict[RuleAction, Callable[[RuleMsg], None]] = {
            RuleAction.INSERT_TABLE_ENTRY: self.__insert_table_entry,
            RuleAction.REMOVE_TABLE_ENTRY: self.__remove_table_entry,
            RuleAction.CREATE_BSM_GRP: self.__create_bsm_grp,
            RuleAction.DESTROY_BSM_GRP: self.__destroy_bsm_grp,
        }

    def __insert_table_entry(self, message: TableInsertMsg) -> None:
        table: Table = self.node.p4device.table(message.block, message.table)
        message.handle = table.insert_entry(message.key, message.action_name, message.action_data)

    def __remove_table_entry(self, message: TableRemoveMsg) -> None:
        table: Table = self.node.p4device.table(message.block, message.table)
        table.remove_entry(message.handle)

    def __create_bsm_grp(self, message: BsmGrpCreateMsg) -> None:
        self.node.p4device.create_bsm_group(
            message.bsm_grp_id, message.bsm_grp_entry_0, message.bsm_grp_entry_1)

    def __destroy_bsm_grp(self, message: BsmGrpDestroyMsg) -> None:
        self.node.p4device.destroy_bsm_group(message.bsm_grp_id)

    def _process(self, items):
        assert items is not None

        for message in items:
            message: QcpMsg
            assert message.msg_type == QcpOp.OP_RULE

            message: RuleMsg
            self.__dispatch[message.rule_action](message)
            self.node.ports[str(CTL_PORT)].tx_output(message)

    def run(self):
        """Run the Agent protocol."""
        port = self.node.ports[str(CTL_PORT)]

        while True:
            yield self.await_port_input(port)
            msg = port.rx_input()

            self._process(msg.items)
