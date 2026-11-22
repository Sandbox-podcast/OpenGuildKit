const assert = require("node:assert");
const test = require("node:test");
const { toCsv } = require("./export");

test("a row becomes a line under the column names", () => {
  assert.strictEqual(toCsv([{ id: 1, title: "Printer offline" }]), "id,title\n1,Printer offline\n");
});

test("a comma or a quote is quoted", () => {
  assert.strictEqual(toCsv([{ title: 'Say "hi", then leave' }]), 'title\n"Say ""hi"", then leave"\n');
});
