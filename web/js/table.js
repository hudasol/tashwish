import { el, t, mlink } from "./common.js";

// Sortable table. columns: [{id, label, methodKey?, value(row)->sortable, cell(row)->Node|string, numeric?}]
// opts: {caption, rowKey, onRowActivate, sort:{id,dir}}
export function sortableTable(columns, rows, opts = {}) {
  const sort = { id: (opts.sort && opts.sort.id) || columns[0].id, dir: (opts.sort && opts.sort.dir) || "asc" };
  const table = el("table", { class: "data" });
  if (opts.caption) table.append(el("caption", { text: opts.caption }));
  const thead = el("thead");
  const trh = el("tr");
  const ths = {};
  columns.forEach((c) => {
    const th = el("th", { scope: "col", class: c.numeric ? "n" : null, "aria-sort": "none" });
    const b = el("button", { type: "button", class: "sortbtn", text: c.label, onclick: () => {
      if (sort.id === c.id) sort.dir = sort.dir === "asc" ? "desc" : "asc"; else { sort.id = c.id; sort.dir = c.numeric ? "desc" : "asc"; }
      paint();
    } });
    th.append(b);
    if (c.methodKey) th.append(" ", mlink(c.methodKey));
    ths[c.id] = th;
    trh.append(th);
  });
  thead.append(trh);
  const tbody = el("tbody");
  table.append(thead, tbody);

  function paint() {
    const col = columns.find((c) => c.id === sort.id) || columns[0];
    const dir = sort.dir === "asc" ? 1 : -1;
    const sorted = rows.slice().sort((a, b) => {
      const va = col.value(a), vb = col.value(b);
      const na = va === null || va === undefined, nb = vb === null || vb === undefined;
      if (na && nb) return 0;
      if (na) return 1;
      if (nb) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb)) * dir;
    });
    columns.forEach((c) => ths[c.id].setAttribute("aria-sort", c.id === col.id ? (sort.dir === "asc" ? "ascending" : "descending") : "none"));
    tbody.textContent = "";
    const frag = document.createDocumentFragment();
    sorted.forEach((r) => {
      const tr = el("tr", opts.rowClass ? { class: opts.rowClass(r) } : null);
      columns.forEach((c, i) => {
        const cell = c.cell(r);
        const td = el(i === 0 ? "th" : "td", { class: c.numeric ? "n" : null, scope: i === 0 ? "row" : null });
        td.append(cell);
        tr.append(td);
      });
      frag.append(tr);
    });
    tbody.append(frag);
    if (opts.onPaint) opts.onPaint(sorted);
  }
  paint();
  return table;
}
