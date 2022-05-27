const bit<9> PORT_CPU = 0x000;

const bit<16> ETHERTYPE_QCP = 0x4400;
const bit<16> ETHERTYPE_EGP = 0x4401;
const bit<16> ETHERTYPE_QNP = 0x4402;

typedef bit<48> mac_addr_t;

header ethernet_t {
    mac_addr_t dst_addr;
    mac_addr_t src_addr;
    bit<16>   ethertype;
}

header egp_t {
    bit<16> link_label;
    bit<16> pair_seq;
    bit<2> bell_index;
    bit<30> _reserved;
}

header qnp_t {
    bit<16> circuit_id;
    bit<16> pair_id;
    bit<2> bell_index;
    bit<30> _reserved;
}

header bsm_info_t {
    bit<16> bsm_id;
    bit<16> outcome_seq;
    bit<1> success;
    bit<2> bell_index;
    bit<29> _reserved;
}
