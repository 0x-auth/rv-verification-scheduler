module t (
  input  wire        clk,
  input  wire [31:0] wide_port_a,
  input  wire [31:0] wide_port_b,
  output reg  [31:0] out
);
  reg [7:0] a, b, c;          // three 8-bit regs = 24 bits
  reg [15:0] d;
  always @(posedge clk) begin
    if (a > b) out <= wide_port_a + wide_port_b;
    else       out <= d;
  end
endmodule
