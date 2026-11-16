module riscv_custom_coprocessor (
    input wire clk,
    input wire rst,
    input wire [31:0] rvvi_pc_if,
    input wire [31:0] rvvi_insn_if,
    output reg custom_valid
);

    always_ff @(posedge clk) begin
        if (rst) begin
            custom_valid <= 1'b0;
        end else if (rvvi_insn_if[6:0] == 7'b0111011) begin
            custom_valid <= 1'b1;
        end else begin
            custom_valid <= 1'b0;
        end
    end

endmodule
