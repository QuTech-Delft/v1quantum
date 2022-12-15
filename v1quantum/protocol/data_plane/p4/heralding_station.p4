/* -*- P4_16 -*- */
#include <core.p4>
#include <v1quantum.p4>

#include "headers.p4"

// The 1 is to allow indexing using the BSM unit index.
const bit<32> BSM_UNITS_MAX = 32;

struct bsm_grp_state_t {
    bit<16> outcome_seq;
    bit<16> pair_seq;
}

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

struct metadata { }

struct headers {
    ethernet_t ethernet;
    egp_t      egp;
    bsm_info_t bsm_info;
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
        packet.extract(hdr.ethernet);
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
        assert(hdr.ethernet.isValid());
        ethernet_tbl.apply();
    }
}

/*************************************************************************
*********  C R O S S - C O N N E C T   P R O C E S S I N G   ************
*************************************************************************/

control xQDevice(
    inout headers hdr,
    inout metadata meta,
    inout qdevice_metadata_t qdevice_metadata,
    inout xconnect_metadata_t xconnect_metadata
) {
    bsm_grp_state_t bsm_grp_state;
    register<bit<16>>(BSM_UNITS_MAX) r_bsm_grp_state_outcome_seq;
    register<bit<16>>(BSM_UNITS_MAX) r_bsm_grp_state_pair_seq;

    action bsm_grp_state_read(bit<32> index) {
        r_bsm_grp_state_outcome_seq.read(bsm_grp_state.outcome_seq, index);
        r_bsm_grp_state_pair_seq.read(bsm_grp_state.pair_seq, index);
    }

    action bsm_grp_state_write(bit<32> index) {
        r_bsm_grp_state_outcome_seq.write(index, bsm_grp_state.outcome_seq);
        r_bsm_grp_state_pair_seq.write(index, bsm_grp_state.pair_seq);
    }

    action bsm_to_egp(bit<16> link_label) {
        // Assign to a request and fill out EGP header.
        hdr.egp.setValid();
        hdr.egp.link_label = link_label;
        hdr.egp.pair_seq = bsm_grp_state.pair_seq;
        hdr.egp.bell_index = qdevice_metadata.bsm_bell_index;

        // Increment pair_seq.
        bsm_grp_state.pair_seq = bsm_grp_state.pair_seq + 1;

        // BSM-cast to qnodes.
        xconnect_metadata.bsm_grp = qdevice_metadata.bsm_id;
    }

    table bsm_tbl {
        key = {
            qdevice_metadata.bsm_id: exact;
            qdevice_metadata.bsm_success: exact;
        }
        actions = {
            bsm_to_egp;
        }
        size = 2*BSM_UNITS_MAX;
    }

    apply {
        // Do not support any other QDevice event
        assert(qdevice_metadata.event_type == QDeviceEventType.heralding_bsm_outcome);

        // Read the BSM group state.
        bsm_grp_state_read((bit<32>)qdevice_metadata.bsm_id);

        // We will be sending a telemetry packet to the CPU so set up ethernet header regardless.
        hdr.ethernet.setValid();
        hdr.ethernet.ethertype = ETHERTYPE_EGP;

        // Execute EGP.
        bsm_tbl.apply();

        // Telemetry.
        hdr.bsm_info.bsm_id = qdevice_metadata.bsm_id;
        hdr.bsm_info.outcome_seq = bsm_grp_state.outcome_seq;
        hdr.bsm_info.success = (qdevice_metadata.bsm_success ? (bit<1>)1 : (bit<1>)0);
        hdr.bsm_info.bell_index = qdevice_metadata.bsm_bell_index;
        xconnect_metadata.egress_spec = PORT_CPU;

        // Increment outcome_seq.
        bsm_grp_state.outcome_seq = bsm_grp_state.outcome_seq + 1;

        // Write the BSM group state.
        bsm_grp_state_write((bit<32>)qdevice_metadata.bsm_id);
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
    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ethernet_address(mac_addr_t dst_addr) {
        hdr.ethernet.dst_addr = dst_addr;
    }

    table ethernet_tbl {
        key = {
            standard_metadata.egress_port: exact;
        }
        actions = {
            ethernet_address;
            drop;
        }
        const default_action = drop();
        const entries = {
            0: ethernet_address(0x000000000000);
        }
    }

    apply {
        if (hdr.ethernet.isValid()) {
            ethernet_tbl.apply();
            if (standard_metadata.egress_port == PORT_CPU) {
                hdr.bsm_info.setValid();
            }
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
        packet.emit(hdr.bsm_info);
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
