interface instruction_bus_if(input bit clk);
    logic [31:0] data;
    logic valid;
    logic ready;
endinterface

module riscv_decoder_advanced (
    input bit clk,
    input bit rst,
    instruction_bus_if bus_in,
    output reg [4:0] dest_reg
);

    typedef struct packed {
        logic [6:0] opcode;
        logic [4:0] rd;
        logic [2:0] funct3;
    } instr_hdr_t;

    instr_hdr_t header;
    assign header = bus_in.data[14:0];

    always_ff @(posedge clk) begin
        if (rst) begin
            dest_reg <= 5'b0;
        end else if (bus_in.valid && bus_in.ready) begin
            if (header.opcode == 7'b0010011) begin
                dest_reg <= header.rd;
            end
        end
    end

endmodule
