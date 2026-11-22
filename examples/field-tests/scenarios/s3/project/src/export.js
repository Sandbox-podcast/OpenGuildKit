// Turns the tracker's rows into CSV text for the operators' spreadsheet.
function cell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(rows) {
  if (rows.length === 0) return "";
  const columns = Object.keys(rows[0]);
  const lines = rows.map((row) => columns.map((column) => cell(row[column])).join(","));
  return [columns.join(","), ...lines].join("\n") + "\n";
}

module.exports = { toCsv };
