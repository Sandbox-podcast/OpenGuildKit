const express = require("express");
const { toCsv } = require("./export");

const app = express();
const requests = [{ id: 1, title: "Printer offline", note: "=HYPERLINK(\"https://example.test\")" }];

app.get("/health", (req, res) => res.json({ ok: true }));
app.get("/export.csv", (req, res) => res.type("text/csv").send(toCsv(requests)));

module.exports = app;
