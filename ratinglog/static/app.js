"use strict";
for (const button of document.querySelectorAll("[data-confirm]")) {
  button.addEventListener("click", (event) => {
    if (!window.confirm(button.dataset.confirm)) event.preventDefault();
  });
}
for (const wrap of document.querySelectorAll("[data-chart]")) {
  const rows = JSON.parse(wrap.dataset.rows);
  const select = wrap.querySelector("[data-series]");
  const groups = new Map();
  for (const row of rows) {
    const key = `${row.sex} / ${row.smoking} / 기간 ${row.duration}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  for (const key of groups.keys()) select.add(new Option(key, key));
  const canvas = wrap.querySelector("canvas");
  function draw() {
    const data = groups
      .get(select.value)
      .slice()
      .sort((a, b) => a.age - b.age);
    const ctx = canvas.getContext("2d");
    const w = canvas.width,
      h = canvas.height,
      pad = 64;
    ctx.clearRect(0, 0, w, h);
    const min = data[0].age,
      max = data[data.length - 1].age;
    const top =
      Math.max(...data.map((r) => Number(r.probability)), 0.000001) * 1.1;
    const x = (age) =>
      pad + ((age - min) / Math.max(max - min, 1)) * (w - pad * 2);
    const y = (value) => h - pad - (value / top) * (h - pad * 2);
    ctx.font = "14px sans-serif";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const value = (top * i) / 4;
      ctx.strokeStyle = "#e8eceb";
      ctx.beginPath();
      ctx.moveTo(pad, y(value));
      ctx.lineTo(w - pad, y(value));
      ctx.stroke();
      ctx.fillStyle = "#64736d";
      ctx.fillText(value.toPrecision(2), 2, y(value) + 4);
    }
    ctx.strokeStyle = "#168267";
    ctx.lineWidth = 3;
    ctx.beginPath();
    // A missing age is a gap, not an interpolated rate.
    data.forEach((row, i) => {
      if (!i || row.age - data[i - 1].age !== 1)
        ctx.moveTo(x(row.age), y(Number(row.probability)));
      else ctx.lineTo(x(row.age), y(Number(row.probability)));
    });
    ctx.stroke();
    ctx.fillStyle = "#168267";
    for (const row of data) {
      ctx.beginPath();
      ctx.arc(x(row.age), y(Number(row.probability)), 4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = "#64736d";
    ctx.fillText(`${min}세`, pad, h - 20);
    ctx.fillText(`${max}세`, w - pad - 25, h - 20);
    wrap.querySelector("[data-chart-summary]").textContent =
      `${select.value} · ${data.length}개 값 · ${min}~${max}세. 누락 연령은 연결하지 않습니다.`;
  }
  select.addEventListener("change", draw);
  draw();
}
