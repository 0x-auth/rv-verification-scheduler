module riscv_decoder_unit (
    input wire clk,
    input wire rst,
    input wire [31:0] instr,
    output reg [4:0] rs1,
    output reg [4:0] rs2,
    output reg [4:0] rd,
    output reg is_alu_imm
);

    // Simple control logic block for base RV32I decoding
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            rs1        <= 5'b0;
            rs2        <= 5'b0;
            rd         <= 5'b0;
            is_alu_imm <= 1'b0;
        end else begin
            case (instr[6:0])
                7'b0010011: begin // OP-IMM
                    rs1        <= instr[19:15];
                    rs2        <= 5'b0;
                    rd         <= instr[11:7];
                    is_alu_imm <= 1'b1;
                end
                7'b0110011: begin // OP
                    rs1        <= instr[19:15];
                    rs2        <= instr[24:20];
                    rd         <= instr[11:7];
                    is_alu_imm <= 1'b0;
                end
                default: begin
                    rs1        <= 5'b0;
                    rs2        <= 5'b0;
                    rd         <= 5'b0;
                    is_alu_imm <= 1'b0;
                end
            endcase
        end
    end

    // Basic SystemVerilog Assertion property tracking
    // property check_rs1_bound;
    //     @(posedge clk) disable iff (rst) (instr[6:0] == 7'b0010011) -> (rs1 == instr[19:15]);
    // endproperty
    // assert property (check_rs1_bound);

endmodule
