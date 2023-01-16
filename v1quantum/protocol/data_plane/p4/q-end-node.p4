/* -*- P4_16 -*- */
#include <core.p4>
#include <v1quantum.p4>

#include "headers.p4"

const bit<9> PORT_END_NODE = 0x001;

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

struct metadata { }

struct headers {
    ethernet_t   ethernet;
    egp_t        egp;
    qnp_t        qnp;
}

/*************************************************************************
*********************** P A R S E R  ***********************************
*************************************************************************/

parser xParser(
    packet_in packet,
    out headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.ethertype) {
            ETHERTYPE_EGP: parse_egp;
            ETHERTYPE_QNP: parse_qnp;
            default: accept;
        }
    }

    state parse_egp {
        packet.extract(hdr.egp);
        transition accept;
    }

    state parse_qnp {
        packet.extract(hdr.egp);
        packet.extract(hdr.qnp);
        transition accept;
    }

}

/*************************************************************************
************   C H E C K S U M    V E R I F I C A T I O N   *************
*************************************************************************/

control xVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}


/*************************************************************************
**************  I N G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control xIngress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata,
    inout xconnect_metadata_t xconnect_metadata
) {
    action drop() {
        mark_to_drop(standard_metadata);
    }

    action forward(bit<9> port) {
        standard_metadata.egress_spec = port;
    }

    table ethernet_tbl {
        key = {
            hdr.ethernet.dst_addr: exact;
        }
        actions = {
            forward;
            drop;
        }
        size = 1024;
        default_action = drop();
    }

    apply {
        if (hdr.egp.isValid()) {
            xconnect_metadata.pathway = PathWay.qcontrol;
        } else {
            assert(hdr.ethernet.isValid());
            ethernet_tbl.apply();
        }
    }
}

/*************************************************************************
***************  Q D E V I C E   P R O C E S S I N G   ******************
*************************************************************************/

control xQControl(
    inout headers hdr,
    inout metadata meta,
    inout qcontrol_metadata_t qcontrol_metadata,
    inout xconnect_metadata_t xconnect_metadata
) {
    action qubit_release() {
        qcontrol_metadata.operation = QControlOperation.release;
        qcontrol_metadata.release_qubit = PORT_END_NODE;
    }

    action egp_to_qnp(bit<16> circuit_id, bit<1> head_end, bit<48> next_mac_addr) {
        // An end-node has only one port.
        xconnect_metadata.egress_spec = PORT_END_NODE;

        // Fill out the ethernet header.
        assert(hdr.ethernet.isValid());
        hdr.ethernet.dst_addr = next_mac_addr;
        hdr.ethernet.ethertype = ETHERTYPE_QNP;

        // We re-use the EGP header that has arrived.
        assert(hdr.egp.isValid());

        // But fill out the QNP header as well.
        hdr.qnp.setValid();
        hdr.qnp.circuit_id = circuit_id;
        hdr.qnp.pair_id = ((head_end == 1) ? hdr.egp.pair_seq : 0);
        hdr.qnp.bell_index = hdr.egp.bell_index;
    }

    action egp_to_cpu() {
        xconnect_metadata.egress_spec = PORT_CPU;
    }

    table egp_tbl {
        key = {
            hdr.egp.link_label: exact;
        }
        actions = {
            egp_to_qnp;
            egp_to_cpu;
            qubit_release;
        }
        default_action = qubit_release();
    }

    action qnp_to_cpu(bit<1> head_end) {
        // Update the pair_seq value if this is the head-end node.
        if (head_end == 1) {
            hdr.qnp.pair_id = hdr.egp.pair_seq;
        }

        // Kick to CPU.
        xconnect_metadata.egress_spec = PORT_CPU;
    }

    table qnp_tbl {
        key = {
            hdr.qnp.circuit_id: exact;
        }
        actions = {
            qnp_to_cpu;
            qubit_release;
        }
        default_action = qubit_release();
    }

    apply {
        if (qcontrol_metadata.event_type == QControlEventType.heralding_bsm_outcome) {
            // TODO: will eventually hold measurement outcome for measure directly.
        } else {
            assert(qcontrol_metadata.event_type == QControlEventType.cnetwork);

            if (hdr.qnp.isValid()) {
                qnp_tbl.apply();
            } else if (hdr.egp.isValid()) {
                egp_tbl.apply();
            }
        }
    }
}

/*************************************************************************
****************  E G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control xEgress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata,
    inout xconnect_metadata_t xconnect_metadata
) {
    apply { }
}

/*************************************************************************
*************   C H E C K S U M    C O M P U T A T I O N   **************
*************************************************************************/

control xComputeChecksum(inout headers  hdr, inout metadata meta) {
    apply { }
}

/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/

control xDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.egp);
        packet.emit(hdr.qnp);
    }
}

/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/

V1Quantum(
    xParser(),
    xVerifyChecksum(),
    xIngress(),
    xQControl(),
    xEgress(),
    xComputeChecksum(),
    xDeparser()
) main;
