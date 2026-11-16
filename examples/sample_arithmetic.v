module riscv_alu_multiplier (
    input wire clk,
    input wire rst,
    input wire [31:0] op_a,
    input wire [31:0] op_b,
    input wire [2:0] alu_sel,
    output reg [63:0] alu_out
);

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            alu_out <= 64'b0;
        end else begin
            case (alu_sel)
                3'b000: alu_out <= op_a + op_b;
                3'b001: alu_out <= op_a - op_b;
                3'b010: alu_out <= op_a * op_b;
                3'b011: alu_out <= (op_b != 0) ? (op_a / op_b) : 64'b0;
                3'b100: alu_out <= op_a << op_b[4:0];
                3'b101: alu_out <= op_a >> op_b[4:0];
                default: alu_out <= 64'b0;
            endcase
        end
    end

endmodule
