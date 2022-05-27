/* -*- P4_16 -*- */
#include <core.p4>
#include <v1quantum.p4>

#include "headers.p4"

const bit<32> PORTS_MAX = 512;
const bit<32> QNP_VC_MAX = (1 << 16);

bit<2> add_bell_index(in bit<2> lhs, in bit<2> rhs) {
    return (
        (((lhs & 0b10) + (rhs & 0b10)) & 0b10) +
        (((lhs & 0b01) + (rhs & 0b01)) & 0b01)
    );
}

struct qnp_vc_state_t {
    bit<16> swap_seq;
}

struct egp_link_swap_info_t {
    bit<16> circuit_id;
    bit<9> other_port;
    bit<16> other_label;
}

struct qnp_forward_info_t {
    bit<9> other_port;
}

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

struct metadata { }

struct headers {
    ethernet_t ethernet;
    egp_t      egp;
    qnp_t      qnp;
    bsm_info_t swap_info;
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
        if (hdr.egp.isValid() || hdr.qnp.isValid()) {
            xconnect_metadata.pathway = PathWay.qdevice;
        } else {
            assert(hdr.ethernet.isValid());
            ethernet_tbl.apply();
        }
    }
}

/*************************************************************************
*********  C R O S S - C O N N E C T   P R O C E S S I N G   ************
*************************************************************************/

register<bit<1>>(PORTS_MAX) r_egp_pending;
register<bit<16>>(PORTS_MAX) r_egp_link_label;
register<bit<16>>(PORTS_MAX) r_egp_pair_seq;
register<bit<2>>(PORTS_MAX) r_egp_bell_index;

control xQDevice(
    inout headers hdr,
    inout metadata meta,
    inout qdevice_metadata_t qdevice_metadata,
    inout xconnect_metadata_t xconnect_metadata
) {
    egp_t egp_state;
    egp_link_swap_info_t egp_link_swap_info;
    qnp_forward_info_t qnp_forward_info;

    action egp_read(bit<32> index) {
        r_egp_link_label.read(egp_state.link_label, index);
        r_egp_pair_seq.read(egp_state.pair_seq, index);
        r_egp_bell_index.read(egp_state.bell_index, index);
    }

    action egp_write(bit<32> index) {
        r_egp_link_label.write(index, egp_state.link_label);
        r_egp_pair_seq.write(index, egp_state.pair_seq);
        r_egp_bell_index.write(index, egp_state.bell_index);
    }

    qnp_vc_state_t qnp_vc_state;
    register<bit<16>>(QNP_VC_MAX) r_qnp_vc_state_swap_seq;

    action qnp_vc_state_read(bit<32> index) {
        r_qnp_vc_state_swap_seq.read(qnp_vc_state.swap_seq, index);
    }

    action qnp_vc_state_write(bit<32> index) {
        r_qnp_vc_state_swap_seq.write(index, qnp_vc_state.swap_seq);
    }

    action qubit_release() {
        qdevice_metadata.operation = QDeviceOperation.release;
        qdevice_metadata.release_qubit = xconnect_metadata.ingress_port;
    }

    action egp_to_qnp(bit<16> circuit_id, bit<9> other_port, bit<16> other_label) {
        egp_link_swap_info.circuit_id = circuit_id;
        egp_link_swap_info.other_port = other_port;
        egp_link_swap_info.other_label = other_label;
    }

    table egp_tbl {
        key = {
            xconnect_metadata.ingress_port: exact;
            hdr.egp.link_label: exact;
        }
        actions = {
            egp_to_qnp;
            qubit_release;
        }
        default_action = qubit_release();
    }

    action qnp_swap_to_track() {
        // Load VC state.
        qnp_vc_state_read((bit<32>)qdevice_metadata.swap_bsm_id);

        // Fill out telemetry info.
        assert(qdevice_metadata.swap_bsm_id == qdevice_metadata.bsm_id);
        hdr.swap_info.setValid();
        hdr.swap_info.bsm_id = qdevice_metadata.bsm_id;
        hdr.swap_info.outcome_seq = qnp_vc_state.swap_seq;
        hdr.swap_info.success = (qdevice_metadata.bsm_success ? (bit<1>)1 : (bit<1>)0);
        hdr.swap_info.bell_index = qdevice_metadata.bsm_bell_index;
        xconnect_metadata.egress_spec = PORT_CPU;

        qnp_vc_state.swap_seq = qnp_vc_state.swap_seq + 1;

        // BSM-cast the results.
        xconnect_metadata.bsm_grp = qdevice_metadata.swap_bsm_id;

        // Write the VC state.
        qnp_vc_state_write((bit<32>)qdevice_metadata.swap_bsm_id);
    }

    action qnp_forward(bit<9> other_port) {
        qnp_forward_info.other_port = other_port;
    }

    table qnp_tbl {
        key = {
            xconnect_metadata.ingress_port: exact;
            hdr.qnp.circuit_id: exact;
        }
        actions = {
            qnp_forward;
            qubit_release;
        }
        default_action = qubit_release();
    }

    apply {
        if (qdevice_metadata.event_type == QDeviceEventType.cnetwork) {
            if (!hdr.qnp.isValid()) {
                assert(hdr.egp.isValid());

                egp_link_swap_info.circuit_id = 0;
                egp_link_swap_info.other_port = 0;
                egp_link_swap_info.other_label = 0;

                switch (egp_tbl.apply().action_run) {
                    egp_to_qnp: {
                        // Regardless what we do, we need to store our EGP information first.
                        r_egp_pending.write((bit<32>)xconnect_metadata.ingress_port, 1);

                        egp_state.link_label = hdr.egp.link_label;
                        egp_state.pair_seq = hdr.egp.pair_seq;
                        egp_state.bell_index = hdr.egp.bell_index;

                        egp_write((bit<32>)xconnect_metadata.ingress_port);

                        // We want to swap so we need to check if the other qubit is here.
                        bit<1> egp_pending_bit;
                        r_egp_pending.read(egp_pending_bit, (bit<32>)egp_link_swap_info.other_port);

                        if (egp_pending_bit == 1) {
                            egp_read((bit<32>)egp_link_swap_info.other_port);

                            // If a qubit is waiting on the other port, we need to make sure it's
                            // for our circuit.
                            if (egp_state.link_label == egp_link_swap_info.other_label) {
                                // If it is we fill out the swap instruction.
                                qdevice_metadata.operation = QDeviceOperation.swap;
                                qdevice_metadata.swap_bsm_id = egp_link_swap_info.circuit_id;
                                qdevice_metadata.swap_qubit_0 = xconnect_metadata.ingress_port;
                                qdevice_metadata.swap_qubit_1 = egp_link_swap_info.other_port;
                            }

                            // Otherwise, we wait. We have already stored our EGP information.

                        }
                    }
                }
            } else {

                qnp_forward_info.other_port = 0;

                switch (qnp_tbl.apply().action_run) {
                    qnp_forward: {
                        xconnect_metadata.egress_spec = qnp_forward_info.other_port;
                    }
                };
            }
        } else if (qdevice_metadata.event_type == QDeviceEventType.swap_bsm_outcome) {
            qnp_swap_to_track();
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
    egp_t egp_state;

    action egp_read(bit<32> index) {
        r_egp_link_label.read(egp_state.link_label, index);
        r_egp_pair_seq.read(egp_state.pair_seq, index);
        r_egp_bell_index.read(egp_state.bell_index, index);
    }

    action egp_write(bit<32> index) {
        r_egp_link_label.write(index, egp_state.link_label);
        r_egp_pair_seq.write(index, egp_state.pair_seq);
        r_egp_bell_index.write(index, egp_state.bell_index);
    }

    qnp_t qnp_state;
    register<bit<1>>(PORTS_MAX) r_qnp_pending;
    register<bit<16>>(PORTS_MAX) r_qnp_circuit_id;
    register<bit<16>>(PORTS_MAX) r_qnp_pair_id;
    register<bit<2>>(PORTS_MAX) r_qnp_bell_index;

    action qnp_read(bit<32> index) {
        r_qnp_circuit_id.read(qnp_state.circuit_id, index);
        r_qnp_pair_id.read(qnp_state.pair_id, index);
        r_qnp_bell_index.read(qnp_state.bell_index, index);
    }

    action qnp_write(bit<32> index) {
        r_qnp_circuit_id.write(index, qnp_state.circuit_id);
        r_qnp_pair_id.write(index, qnp_state.pair_id);
        r_qnp_bell_index.write(index, qnp_state.bell_index);
    }

    bsm_info_t swap_info;
    register<bit<1>>(PORTS_MAX) r_swap_info_pending;
    register<bit<16>>(PORTS_MAX) r_swap_info_bsm_id;
    register<bit<16>>(PORTS_MAX) r_swap_info_outcome_seq;
    register<bit<1>>(PORTS_MAX) r_swap_info_success;
    register<bit<2>>(PORTS_MAX) r_swap_info_bell_index;

    action swap_info_read(bit<32> index) {
        r_swap_info_bsm_id.read(swap_info.bsm_id, index);
        r_swap_info_outcome_seq.read(swap_info.outcome_seq, index);
        r_swap_info_success.read(swap_info.success, index);
        r_swap_info_bell_index.read(swap_info.bell_index, index);
    }

    action swap_info_write(bit<32> index) {
        r_swap_info_bsm_id.write(index, swap_info.bsm_id);
        r_swap_info_outcome_seq.write(index, swap_info.outcome_seq);
        r_swap_info_success.write(index, swap_info.success);
        r_swap_info_bell_index.write(index, swap_info.bell_index);
    }

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ethernet_address(mac_addr_t dst_addr) {
        hdr.ethernet.dst_addr = dst_addr;
    }

    table ethernet_tbl {
        key = {
            standard_metadata.egress_port: exact;
            hdr.qnp.circuit_id: exact;
        }
        actions = {
            ethernet_address;
            drop;
        }
        const default_action = drop();
    }

    apply {
        if ((standard_metadata.egress_port != PORT_CPU) && hdr.swap_info.isValid()) {
            // Check if a track has arrived from the other side.
            bit<1> qnp_pending_bit;
            r_qnp_pending.read(qnp_pending_bit, (bit<32>)xconnect_metadata.bsm_info);

            // Get the QNP header from where it came from.
            qnp_read((bit<32>)xconnect_metadata.bsm_info);

            if ((qnp_pending_bit == 1) && (hdr.swap_info.bsm_id == qnp_state.circuit_id)) {

                // The QNP header is no longer pending.
                r_qnp_pending.write((bit<32>)xconnect_metadata.bsm_info, 0);

                // But the EGP header in the direction we're heading into.
                egp_read((bit<32>)standard_metadata.egress_port);
                r_egp_pending.write((bit<32>)standard_metadata.egress_port, 0);

                // Set up the ethernet header.
                hdr.ethernet.setValid();
                hdr.ethernet.ethertype = ETHERTYPE_QNP;

                // Use the EGP header of the link we're heading into.
                hdr.egp.setValid();
                hdr.egp.link_label = egp_state.link_label;
                hdr.egp.pair_seq = egp_state.pair_seq;
                hdr.egp.bell_index = egp_state.bell_index;

                // And finally the QNP header.
                hdr.qnp.setValid();
                hdr.qnp.circuit_id = qnp_state.circuit_id;
                hdr.qnp.pair_id = qnp_state.pair_id;
                hdr.qnp.bell_index = add_bell_index(qnp_state.bell_index, hdr.swap_info.bell_index);
                hdr.qnp.bell_index = add_bell_index(hdr.qnp.bell_index, hdr.egp.bell_index);

            } else {
                // If there is no QNP message for our circuit we store the swap information.
                swap_info.bsm_id = hdr.swap_info.bsm_id;
                swap_info.outcome_seq = hdr.swap_info.outcome_seq;
                swap_info.success = hdr.swap_info.success;
                swap_info.bell_index = hdr.swap_info.bell_index;
                swap_info_write((bit<32>)standard_metadata.egress_port);
                r_swap_info_pending.write((bit<32>)standard_metadata.egress_port, 1);

                // No packet is sent out as the ethernet header hasn't been added.
            }

            // The swap info header only stays valid for the CPU port.
            hdr.swap_info.setInvalid();

        } else if (hdr.qnp.isValid()) {
            // Check if there is a swap pending.
            bit<1> swap_info_pending_bit;
            r_swap_info_pending.read(swap_info_pending_bit, (bit<32>)standard_metadata.egress_port);
            swap_info_read((bit<32>)standard_metadata.egress_port);

            if ((swap_info_pending_bit == 1) && (hdr.qnp.circuit_id == swap_info.bsm_id)) {

                // The swap info is no longer pending.
                r_swap_info_pending.write((bit<32>)standard_metadata.egress_port, 0);

                // But the EGP header in the direction we're heading into.
                egp_read((bit<32>)standard_metadata.egress_port);
                r_egp_pending.write((bit<32>)standard_metadata.egress_port, 0);

                // Set up the ethernet header.
                assert(hdr.ethernet.isValid());
                assert(hdr.ethernet.ethertype == ETHERTYPE_QNP);

                // Use the EGP header of the link we're heading into.
                assert(hdr.egp.isValid());
                hdr.egp.link_label = egp_state.link_label;
                hdr.egp.pair_seq = egp_state.pair_seq;
                hdr.egp.bell_index = egp_state.bell_index;

                // And finally the QNP header.
                assert(hdr.qnp.isValid());
                hdr.qnp.bell_index = add_bell_index(hdr.qnp.bell_index, swap_info.bell_index);
                hdr.qnp.bell_index = add_bell_index(hdr.qnp.bell_index, hdr.egp.bell_index);

            } else {
                // Otherwise we store the information.
                qnp_state.circuit_id = hdr.qnp.circuit_id;
                qnp_state.pair_id = hdr.qnp.pair_id;
                qnp_state.bell_index = hdr.qnp.bell_index;
                qnp_write((bit<32>)standard_metadata.ingress_port);
                r_qnp_pending.write((bit<32>)standard_metadata.ingress_port, 1);

                // Make sure the packet doesn't get sent out.
                drop();
            }
        }

        if ((standard_metadata.egress_port == PORT_CPU) && hdr.swap_info.isValid()) {
            hdr.ethernet.setValid();
            hdr.ethernet.dst_addr = 0x0;
            hdr.ethernet.ethertype = ETHERTYPE_QNP;
        } else if (hdr.ethernet.isValid() && hdr.qnp.isValid()) {
            ethernet_tbl.apply();
        } else {
            drop();
        }
    }
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
        packet.emit(hdr.swap_info);
    }
}

/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/

V1Quantum(
    xParser(),
    xVerifyChecksum(),
    xIngress(),
    xQDevice(),
    xEgress(),
    xComputeChecksum(),
    xDeparser()
) main;
