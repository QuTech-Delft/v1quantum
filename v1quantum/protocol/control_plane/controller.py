"""The centralised network controller protocol."""

from collections import defaultdict, OrderedDict
from dataclasses import dataclass
import copy
import logging
from typing import DefaultDict, List, Dict, Tuple, Optional, Set

from netsquid.protocols.nodeprotocols import NodeProtocol
import networkx as nx
from pydynaa import EventHandler, EventType
from netsquid_netrunner.generators.network import LinkPort

from experiments.qrx.generate import topology as qrx_topology
from v1quantum.protocol.control_plane.protocol import (
    BsmGrpCreateMsg,
    BsmGrpDestroyMsg,
    QcpMsg,
    QcpOp,
    RequestMsg,
    RuleAction,
    RuleMsg,
    TableInsertMsg,
    TableRemoveMsg,
)
from v1quantum.processor import BsmGroupEntry


logger = logging.getLogger(__name__)


class Routing:
    """Controller routing application."""

    def __init__(self):
        self.__graph: nx.Graph = nx.Graph()
        self.__links: DefaultDict[str, Dict[str, int]] = defaultdict(dict)
        self.__ports: DefaultDict[str, Dict[int, str]] = defaultdict(dict)
        self.__nodes: List[str] = []
        self.__routes: Optional[Dict[str, Dict[str, List[str]]]] = None

    @property
    def routes(self) -> Dict[str, Dict[str, List[str]]]:
        "`Dict[str, Dict[str, List[str]]]`: Shortest path routes between all nodes."
        assert self.__routes is not None
        return self.__routes

    @property
    def nodes(self) -> List[str]:
        "`List[str]`: The list of nodes in the graph."
        return self.__nodes

    def egress(self, src: str, dst: str) -> int:
        """Get the egress port towards a particular destination.

        Parameters
        ----------
        src : `str`
            The node on which we want to know the egress port.
        dst : `str`
            The destination node towards which we want to know the egress.

        Returns
        -------
        `int`
            The egress port towards the destination.

        """
        if dst not in self.__routes[src]:
            return None
        route = self.__routes[src][dst]
        next_hop = route[1] if len(route) > 1 else route[0]
        return self.__links[src][next_hop]

    def ports(self, node: str) -> Dict[int, str]:
        """Get the port->neighbour mapping.

        Returns
        -------
        `Dict[int, str]`
            The outgoing port -> neighbour mapping.
        """
        return self.__ports[node]

    def __add_node(self, name: str) -> None:
        self.__nodes.append(name)
        self.__graph.add_node(name)
        self.__links[name][name] = 0

    def add_controller(self) -> None:
        """Add a controller to the graph."""

    def add_router(self, name: str, *_args, **_kwargs) -> None:
        """Add a router to the graph."""
        self.__add_node(name)

    def add_repeater(self, name: str, *_args, **_kwargs) -> None:
        """Add a repeater to the graph."""
        self.__add_node(name)

    def add_heralding_station(self, name: str, *_args, **_kwargs) -> None:
        """Add a heralding station to the graph."""
        self.__add_node(name)

    def add_host(self, name: str, *_args, **_kwargs) -> None:
        """Add a host to the graph."""
        self.__add_node(name)

    def connect_classical(self, *_args, **_kwargs) -> None:
        return

    def connect_quantum(
            self,
            link_port_1: LinkPort,
            link_port_2: LinkPort,
            _properties: Dict = None,
    ) -> None:
        """Add the provided link to the graph."""
        port_1 = int(link_port_1.port[3:])
        port_2 = int(link_port_2.port[3:])
        self.__links[link_port_1.comp][link_port_2.comp] = port_1
        self.__links[link_port_2.comp][link_port_1.comp] = port_2
        self.__ports[link_port_1.comp][port_1] = link_port_2.comp
        self.__ports[link_port_2.comp][port_2] = link_port_1.comp
        self.__graph.add_edge(link_port_1.comp, link_port_2.comp)

    def compute_routes(self) -> None:
        """Compute the shortest paths for the current graph."""
        self.__routes = nx.shortest_path(self.__graph)  # pylint: disable=no-value-for-parameter


@dataclass
class TableHandle:
    """Table entry handle."""
    node: str
    block: str
    table: str
    handle: int


@dataclass
class BsmGrpHandle:
    """BSM group handle."""
    node: str
    bsm_grp_id: int


@dataclass
class RouteHandles:
    """Table and BSM group entry handles."""
    tables: List[TableHandle]
    bsm_grps: List[BsmGrpHandle]


@dataclass
class ActiveCircuit:
    """An active circuit."""
    circuit_id: int
    pair: Tuple[str, str]


class Controller(NodeProtocol):
    """A central network controller protocol.

    Parameters
    ----------
    node : `~netsquid.nodes.Node`
        The NetSquid node that will run the controller protocol.

    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, node, *_args, **_kwargs):
        super().__init__(node, f"{node.name}-controller")

        # ------------------------------------------------------------------------------------------
        # State used for path reservation.
        # ------------------------------------------------------------------------------------------

        self._pending: Dict[str, Dict[int, RequestMsg]] = {}
        self._reserve_queue: OrderedDict = OrderedDict()
        self._release_queue: List[RequestMsg] = []
        self._installing: Dict[ActiveCircuit] = {}
        self._active: Dict[ActiveCircuit] = {}

        # ------------------------------------------------------------------------------------------
        # Keep track of in flight messages.
        # ------------------------------------------------------------------------------------------

        self.__next_rule_id: int = 0
        self.__reserve_msgs: DefaultDict[int, Set[int]] = DefaultDict(set)
        self.__release_msgs: DefaultDict[int, Set[int]] = DefaultDict(set)

        # ------------------------------------------------------------------------------------------
        # Route computation.
        # ------------------------------------------------------------------------------------------

        self._route_computation()

        # ------------------------------------------------------------------------------------------
        # Generate node addresses.
        # ------------------------------------------------------------------------------------------

        ethaddr_base: int = 0xA0B0A0B00000
        self.__ethaddr: Dict[str, int] = {
            name: (ethaddr_base + ii) for ii, name in enumerate(self._routing.nodes)
        }

        # ------------------------------------------------------------------------------------------
        # Keep handles of inserted entries for each node so that they can be removed later.
        # ------------------------------------------------------------------------------------------

        self.__handles: Dict[int, RouteHandles] = {}

        # ------------------------------------------------------------------------------------------
        # Static setup.
        # ------------------------------------------------------------------------------------------

        self.__static_path_setup()

    def _route_computation(self):
        self._routing: Routing = Routing()
        qrx_topology(self._routing)
        self._routing.compute_routes()

    def _assign_bsm_grp_id(self, _node):
        return 0

    def _release_bsm_grp_id(self, node, bsm_grp_id):
        if not node.startswith("qrx"):
            assert bsm_grp_id == 0

    def __assign_rule_id(self):
        rule_id = self.__next_rule_id
        self.__next_rule_id += 1
        return rule_id

    def run(self):
        """Listen on all the ports and pass messages to handlers."""

        while True:
            # Listen on all ports.
            event = None
            for port in self.node.ports.values():
                if event is None:
                    event = self.await_port_input(port)
                else:
                    event |= self.await_port_input(port)
            yield event

            for port in self.node.ports.values():
                msg = port.rx_input()

                # Because we must loop through all the ports to figure out which one triggered the
                # event, some of them will return None.
                if msg is not None:
                    assert msg.items is not None
                    for item in msg.items:
                        message: QcpMsg = item

                        if message.msg_type in (QcpOp.OP_RSRV, QcpOp.OP_FREE):
                            self.__request_msg(message)
                        elif message.msg_type in (QcpOp.OP_RULE,):
                            self.__rule_msg(message)
                        else:
                            # Unimplemented
                            assert False

    def __request_msg(self, message: RequestMsg):
        # This function processes the incoming message and effectively declares what the desired
        # state is by populatting the self._reserve_queue and self._release_queue collections.
        assert message.msg_type in (QcpOp.OP_RSRV, QcpOp.OP_FREE)

        # Make a note that a host is requesting a connection with a particular remote.
        if message.source in self._pending:
            assert message.request_id not in self._pending[message.source]
        else:
            self._pending[message.source] = {}
        self._pending[message.source][message.request_id] = message

        # If the remote has already asked for the same connection, connect them.
        if (message.remote in self._pending and
                message.request_id in self._pending[message.remote] and
                self._pending[message.remote][message.request_id].remote == message.source):
            assert message.msg_type == self._pending[message.remote][message.request_id].msg_type
            assert message.request_id == \
                self._pending[message.remote][message.request_id].request_id

            if message.msg_type == QcpOp.OP_RSRV:
                rsrv_id = (message.request_id, *sorted((message.source, message.remote)))
                assert rsrv_id not in self._reserve_queue
                self._reserve_queue[rsrv_id] = message
            else:
                assert message.msg_type == QcpOp.OP_FREE
                self._release_queue.append(message)

            del self._pending[message.source][message.request_id]
            if not self._pending[message.source]:
                del self._pending[message.source]

            del self._pending[message.remote][message.request_id]
            if not self._pending[message.remote]:
                del self._pending[message.remote]

        # Process the reservations.
        self._reserve_release()

    def __rule_msg(self, message: RuleMsg):
        if message.rule_action in (RuleAction.INSERT_TABLE_ENTRY, RuleAction.CREATE_BSM_GRP):
            assert message.rule_id in self.__reserve_msgs[message.circuit_id]

            if message.rule_action == RuleAction.INSERT_TABLE_ENTRY:
                message: TableInsertMsg
                assert message.handle is not None
                self.__handles[message.circuit_id].tables.append(
                    TableHandle(message.node, message.block, message.table, message.handle))
            else:
                assert message.rule_action == RuleAction.CREATE_BSM_GRP
                message: BsmGrpCreateMsg
                self.__handles[message.circuit_id].bsm_grps.append(
                    BsmGrpHandle(message.node, message.bsm_grp_id))

            self.__reserve_msgs[message.circuit_id].remove(message.rule_id)

            # Check if this was the last message at which point the installation is complete.
            if not self.__reserve_msgs[message.circuit_id]:
                del self.__reserve_msgs[message.circuit_id]

                # Notify the nodes.
                self._notify(RequestMsg(
                    msg_type=QcpOp.OP_RSRV,
                    source=self._installing[message.circuit_id].pair[0],
                    remote=self._installing[message.circuit_id].pair[1],
                    request_id=message.circuit_id,
                ))

                # And mark as active.
                self._active[message.circuit_id] = self._installing[message.circuit_id]
                del self._installing[message.circuit_id]

                # Schedule a __reserve_release if that was the last message.
                self._wait_once(
                    EventHandler(lambda _: self._reserve_release()),
                    entity=self,
                    event=self._schedule_now(EventType("__RESERVE_RELEASE", "__reserve_release")),
                )

        else:
            assert message.rule_action in (
                RuleAction.REMOVE_TABLE_ENTRY, RuleAction.DESTROY_BSM_GRP)
            assert message.rule_id in self.__release_msgs[message.circuit_id]

            self.__release_msgs[message.circuit_id].remove(message.rule_id)

            # Check if this was the last message at which point removal is complete.
            if not self.__release_msgs[message.circuit_id]:
                del self.__release_msgs[message.circuit_id]

                # Notify the nodes.
                self._notify(RequestMsg(
                    msg_type=QcpOp.OP_FREE,
                    source=self._active[message.circuit_id].pair[0],
                    remote=self._active[message.circuit_id].pair[1],
                    request_id=message.circuit_id,
                ))

                # And deactivate.
                del self._active[message.circuit_id]

                # Schedule a __reserve_release if that was the last message.
                self._wait_once(
                    EventHandler(lambda _: self._reserve_release()),
                    entity=self,
                    event=self._schedule_now(EventType("__RESERVE_RELEASE", "__reserve_release")),
                )

    def _reserve_release(self):
        # First process the releases.
        while self._release_queue:
            message = self._release_queue.pop()
            pair = tuple(sorted((message.source, message.remote)))
            rsrv_id = (message.request_id, *pair)

            if message.request_id in self._active:
                assert pair == self._active[message.request_id].pair
                # The circuit is active and needs to be released. If it is installing, we must wait
                # until it finishes installing as otherwise we won't have the handles.
                self._release(message)

            elif rsrv_id in self._reserve_queue:
                # Circuit is not active, but is queued up. Remove it from the queue.
                del self._reserve_queue[rsrv_id]
                self._notify(message)

            else:
                # Log any leftover releases. This shouldn't happen if the nodes are behaving.
                logger.warning("No match for RELEASE of %s", pair)

        # And finally, if there is no active circuit, install the next one that is queued up.
        while self._reserve_queue and (not self._active) and (not self._installing):
            _, message = self._reserve_queue.popitem()
            self._reserve(message)

    def _reserve(self, message: RequestMsg):
        assert message.request_id not in self._installing
        assert message.request_id not in self._active
        self._installing[message.request_id] = ActiveCircuit(
            circuit_id=message.request_id,
            pair=tuple(sorted((message.source, message.remote))),
        )
        self.__install_path(cid=message.request_id, src=message.source, dst=message.remote)

    def _release(self, message: RequestMsg):
        assert message.request_id not in self._installing
        assert message.request_id in self._active
        assert self._active[message.request_id].pair == \
            tuple(sorted((message.source, message.remote)))
        self.__uninstall_path(message.request_id)

    def _notify(self, message):
        self.node.ports[message.source].tx_output(copy.deepcopy(message))

        message.source, message.remote = message.remote, message.source
        self.node.ports[message.source].tx_output(message)

    def __node_type(self, node):
        return self.node.network_config["components"][node]["type"]

    def __static_path_setup(self):
        # ------------------------------------------------------------------------------------------
        # Static path setup.
        # ------------------------------------------------------------------------------------------

        for dst, dst_addr in self.__ethaddr.items():
            for src in self.__ethaddr.keys():
                egress = self._routing.egress(src, dst)
                if egress is not None:
                    self.node.ether.network_objects["components"][src].p4device.table(
                        "ingress", "xIngress.ethernet_tbl",
                    ).insert_entry(
                        key=dst_addr,
                        action_name="xIngress.forward",
                        action_data=[egress],
                    )

        heralding_stations = list(dict(filter(
            lambda kv: kv[1]["type"] == "heralding_station",
            self.node.network_config["components"].items()
        )).keys())

        for station in heralding_stations:
            for port, dst in self._routing.ports(station).items():
                self.node.ether.network_objects["components"][station].p4device.table(
                    "egress", "xEgress.ethernet_tbl",
                ).insert_entry(
                    key=port,
                    action_name="xEgress.ethernet_address",
                    action_data=[self.__ethaddr[dst]],
                )

    def __install_path(self, cid: int, src: str, dst: str):

        # ------------------------------------------------------------------------------------------
        # Get the route.
        # ------------------------------------------------------------------------------------------

        route: List[str] = self._routing.routes[src][dst]
        assert len(route) >= 3
        assert (len(route) % 2) == 1
        self.__handles[cid] = RouteHandles(tables=[], bsm_grps=[])

        # ------------------------------------------------------------------------------------------
        # Go along path, installing rules node by node.
        # ------------------------------------------------------------------------------------------

        label = 0x10
        for n_i, node in enumerate(route):

            # --------------------------------------------------------------------------------------
            # If the node is a host.
            # --------------------------------------------------------------------------------------

            if self.__node_type(node) == "host":
                assert n_i in (0, len(route) - 1)
                self.__install_path_node(cid, route, n_i, label)

            # --------------------------------------------------------------------------------------
            # Heralding station next.
            # --------------------------------------------------------------------------------------

            if self.__node_type(node) == "heralding_station":
                assert (n_i % 2) == 1
                self.__install_path_heralding_station(cid, route, n_i, label)

            # --------------------------------------------------------------------------------------
            # And repeaters/routers last.
            # --------------------------------------------------------------------------------------

            if self.__node_type(node) in ("repeater", "router"):
                assert (n_i % 2) == 0

                lbl_l = label
                label += 0x10
                lbl_r = label

                self.__install_path_router(cid, route, n_i, lbl_l, lbl_r)

    def __install_path_node(
            self,
            cid: int,
            route: List[str],
            n_i: int,
            label: int,
    ) -> None:
        node = route[n_i]
        head_end = (n_i == 0)
        remote = route[n_i + 2] if head_end else route[n_i - 2]

        message = TableInsertMsg(
            msg_type=QcpOp.OP_RULE,
            circuit_id=cid,
            node=node,
            rule_id=self.__assign_rule_id(),
            rule_action=RuleAction.INSERT_TABLE_ENTRY,
            block="qdevice",
            table="xQDevice.egp_tbl",
            key=label,
            action_name="xQDevice.egp_to_qnp",
            action_data=[cid, int(head_end), self.__ethaddr[remote]],
        )
        self.node.ports[node].tx_output(message)
        self.__reserve_msgs[cid].add(message.rule_id)

        message = TableInsertMsg(
            msg_type=QcpOp.OP_RULE,
            circuit_id=cid,
            node=node,
            rule_id=self.__assign_rule_id(),
            rule_action=RuleAction.INSERT_TABLE_ENTRY,
            block="qdevice",
            table="xQDevice.qnp_tbl",
            key=cid,
            action_name="xQDevice.qnp_to_cpu",
            action_data=[int(head_end)],
        )
        self.node.ports[node].tx_output(message)
        self.__reserve_msgs[cid].add(message.rule_id)

    def __install_path_heralding_station(
            self,
            cid: int,
            route: List[str],
            n_i: int,
            label: int,
    ) -> None:
        node = route[n_i]

        port_l = self._routing.egress(node, route[n_i - 1])
        port_r = self._routing.egress(node, route[n_i + 1])
        bsm_grp_entry_0 = BsmGroupEntry(egress_port=port_l, bsm_info=port_r)
        bsm_grp_entry_1 = BsmGroupEntry(egress_port=port_r, bsm_info=port_l)
        bsm_grp_id = self._assign_bsm_grp_id(node)

        message = BsmGrpCreateMsg(
            msg_type=QcpOp.OP_RULE,
            circuit_id=cid,
            node=node,
            rule_id=self.__assign_rule_id(),
            rule_action=RuleAction.CREATE_BSM_GRP,
            bsm_grp_id=bsm_grp_id,
            bsm_grp_entry_0=bsm_grp_entry_0,
            bsm_grp_entry_1=bsm_grp_entry_1,
        )
        self.node.ports[node].tx_output(message)
        self.__reserve_msgs[cid].add(message.rule_id)

        message = TableInsertMsg(
            msg_type=QcpOp.OP_RULE,
            circuit_id=cid,
            node=node,
            rule_id=self.__assign_rule_id(),
            rule_action=RuleAction.INSERT_TABLE_ENTRY,
            block="qdevice",
            table="xQDevice.bsm_tbl",
            key=[bsm_grp_id, int(True)],
            action_name="xQDevice.bsm_to_egp",
            action_data=[label],
        )
        self.node.ports[node].tx_output(message)
        self.__reserve_msgs[cid].add(message.rule_id)

    def __install_path_router(
            self,
            cid: int,
            route: List[str],
            n_i: int,
            lbl_l: int,
            lbl_r: int,
    ) -> None:
        # pylint: disable=too-many-arguments

        node = route[n_i]
        port_l = self._routing.egress(node, route[n_i - 2])
        port_r = self._routing.egress(node, route[n_i + 2])

        message = BsmGrpCreateMsg(
            msg_type=QcpOp.OP_RULE,
            circuit_id=cid,
            node=node,
            rule_id=self.__assign_rule_id(),
            rule_action=RuleAction.CREATE_BSM_GRP,
            bsm_grp_id=cid,
            bsm_grp_entry_0=BsmGroupEntry(egress_port=port_l, bsm_info=port_r),
            bsm_grp_entry_1=BsmGroupEntry(egress_port=port_r, bsm_info=port_l),
        )
        self.node.ports[node].tx_output(message)
        self.__reserve_msgs[cid].add(message.rule_id)

        for port, other_port, lbl, other_lbl, remote in (
                (port_l, port_r, lbl_l, lbl_r, route[n_i - 2]),
                (port_r, port_l, lbl_r, lbl_l, route[n_i + 2])
        ):
            message = TableInsertMsg(
                msg_type=QcpOp.OP_RULE,
                circuit_id=cid,
                node=node,
                rule_id=self.__assign_rule_id(),
                rule_action=RuleAction.INSERT_TABLE_ENTRY,
                block="qdevice",
                table="xQDevice.egp_tbl",
                key=[port, lbl],
                action_name="xQDevice.egp_to_qnp",
                action_data=[cid, other_port, other_lbl],
            )
            self.node.ports[node].tx_output(message)
            self.__reserve_msgs[cid].add(message.rule_id)

            message = TableInsertMsg(
                msg_type=QcpOp.OP_RULE,
                circuit_id=cid,
                node=node,
                rule_id=self.__assign_rule_id(),
                rule_action=RuleAction.INSERT_TABLE_ENTRY,
                block="qdevice",
                table="xQDevice.qnp_tbl",
                key=[port, cid],
                action_name="xQDevice.qnp_forward",
                action_data=[other_port],
            )
            self.node.ports[node].tx_output(message)
            self.__reserve_msgs[cid].add(message.rule_id)

            message = TableInsertMsg(
                msg_type=QcpOp.OP_RULE,
                circuit_id=cid,
                node=node,
                rule_id=self.__assign_rule_id(),
                rule_action=RuleAction.INSERT_TABLE_ENTRY,
                block="egress",
                table="xEgress.ethernet_tbl",
                key=[port, cid],
                action_name="xEgress.ethernet_address",
                action_data=[self.__ethaddr[remote]],
            )
            self.node.ports[node].tx_output(message)
            self.__reserve_msgs[cid].add(message.rule_id)

    def __uninstall_path(self, cid):

        assert not self.__release_msgs[cid]

        while self.__handles[cid].tables:
            table_handle = self.__handles[cid].tables.pop()
            message = TableRemoveMsg(
                msg_type=QcpOp.OP_RULE,
                circuit_id=cid,
                node=table_handle.node,
                rule_id=self.__assign_rule_id(),
                rule_action=RuleAction.REMOVE_TABLE_ENTRY,
                block=table_handle.block,
                table=table_handle.table,
                handle=table_handle.handle,
            )
            self.node.ports[table_handle.node].tx_output(message)
            self.__release_msgs[cid].add(message.rule_id)

        while self.__handles[cid].bsm_grps:
            bsm_grp_handle = self.__handles[cid].bsm_grps.pop()
            message = BsmGrpDestroyMsg(
                msg_type=QcpOp.OP_RULE,
                circuit_id=cid,
                node=bsm_grp_handle.node,
                rule_id=self.__assign_rule_id(),
                rule_action=RuleAction.DESTROY_BSM_GRP,
                bsm_grp_id=bsm_grp_handle.bsm_grp_id,
            )
            self.node.ports[bsm_grp_handle.node].tx_output(message)
            self.__release_msgs[cid].add(message.rule_id)
            self._release_bsm_grp_id(table_handle.node, bsm_grp_handle.bsm_grp_id)


class HubController(Controller):

    def __init__(self, node, *_args, **_kwargs):
        self.__hosts = set()
        super().__init__(node, *_args, **_kwargs)
        self.__bsm_grp_id_set = set(range(
            self.node.network_config["components"]["qhs"]["properties"]["num_bsm_units"]
        ))
        self.__reserved_hosts = {}

    def _route_computation(self):
        self._routing: Routing = Routing()

        num_heralding_stations = 0
        for component, properties in self.node.network_config["components"].items():
            if properties["type"] == "heralding_station":
                assert component == "qhs"
                num_heralding_stations += 1
            elif properties["type"] == "host":
                self.__hosts.add(component)
            else:
                assert properties["type"] in set(
                    ["controller", "classical_connection", "quantum_connection"]
                )

        assert num_heralding_stations == 1
        assert len(self.__hosts) >= 2

        topologies.star.main(self._routing, 0, len(self.__hosts))
        self._routing.compute_routes()

    def _assign_bsm_grp_id(self, _node):
        return self.__bsm_grp_id_set.pop()

    def _release_bsm_grp_id(self, _node, bsm_grp_id):
        assert bsm_grp_id not in self.__bsm_grp_id_set
        self.__bsm_grp_id_set.add(bsm_grp_id)

    def _reserve_release(self):
        # Release the hosts that are no longer active.
        active_cids = set(self._active.keys()) | set(self._installing.keys())
        free_cids = set(self.__reserved_hosts.keys()) - active_cids
        for cid in free_cids:
            pair = self.__reserved_hosts.pop(cid)
            self.__hosts.add(pair[0])
            self.__hosts.add(pair[1])

        # Process the releases.
        while self._release_queue:
            message = self._release_queue.pop()
            pair = tuple(sorted((message.source, message.remote)))
            rsrv_id = (message.request_id, *pair)

            assert pair[0] not in self.__hosts
            assert pair[1] not in self.__hosts

            if message.request_id in self._active:
                assert pair == self._active[message.request_id].pair
                # The circuit is active and needs to be released. If it is installing, we must wait
                # until it finishes installing as otherwise we won't have the handles.
                self._release(message)

            elif rsrv_id in self._reserve_queue:
                # Circuit is not active, but is queued up. Remove it from the queue.
                del self._reserve_queue[rsrv_id]
                self._notify(message)

            else:
                # Log any leftover releases. This shouldn't happen if the nodes are behaving.
                logger.warning("No match for RELEASE of %s", pair)

        # And finally, if there is no active circuit, install the next one that is queued up.
        while self._reserve_queue and self.__bsm_grp_id_set:
            next_rsrv_id = None

            for rsrv_id, message in self._reserve_queue.items():
                pair = (rsrv_id[1], rsrv_id[2])
                if (pair[0] in self.__hosts) and (pair[1] in self.__hosts):
                    next_rsrv_id = rsrv_id

                    self.__hosts.remove(pair[0])
                    self.__hosts.remove(pair[1])

                    assert rsrv_id[0] == message.request_id
                    assert rsrv_id[0] not in self.__reserved_hosts
                    self.__reserved_hosts[rsrv_id[0]] = pair

                    self._reserve(message)
                    break

            if next_rsrv_id is None:
                break

            del self._reserve_queue[next_rsrv_id]
