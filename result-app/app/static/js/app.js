(function () {
  function css(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  var palette = [
    css("--krds-color-light-secondary-60", "#1c589c"),
    "#6b96c7", "#0b8f8c", "#c9821c", "#8a949e", "#052b57"
  ];

  function render(el) {
    if (!window.echarts || el.dataset.ready) return;
    var cfg = JSON.parse(el.dataset.chart);
    var chart = echarts.init(el);
    var unit = cfg.unit || "";
    var opt = {
      color: palette,
      animation: false,
      textStyle: { fontFamily: "Pretendard GOV, sans-serif" },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: function (v) { return v.toLocaleString() + unit; } },
      grid: { left: 8, right: 32, top: 16, bottom: 8, containLabel: true }
    };

    if (cfg.type === "bar-h") {
      opt.xAxis = { type: "value", axisLabel: { formatter: "{value}" + unit } };
      opt.yAxis = { type: "category", data: cfg.labels };
      opt.series = [{ type: "bar", data: cfg.values, barMaxWidth: 28, label: { show: true, position: "right", formatter: "{c}" + unit } }];
    } else if (cfg.type === "bar-group") {
      opt.legend = { bottom: 0 };
      opt.grid.bottom = 40;
      opt.xAxis = { type: "category", data: cfg.labels };
      opt.yAxis = { type: "value" };
      opt.series = cfg.series.map(function (s) { return { name: s.name, type: "bar", data: s.data, barMaxWidth: 24 }; });
    }

    chart.setOption(opt);
    el.dataset.ready = "1";
    window.addEventListener("resize", function () { chart.resize(); });
  }

  function renderAll(root) {
    (root || document).querySelectorAll("[data-chart]").forEach(render);
  }

  function startSessionTimer() {
    var el = document.querySelector(".rv-session");
    if (!el) return;
    var total = parseInt(el.dataset.minutes, 10) * 60;
    var left = total;
    var out = el.querySelector("strong");
    function tick() {
      left -= 1;
      if (left <= 0) { window.location.href = "/login?expired=1"; return; }
      var m = Math.floor(left / 60), s = left % 60;
      out.textContent = m + ":" + (s < 10 ? "0" : "") + s;
    }
    setInterval(tick, 1000);
    document.body.addEventListener("htmx:afterRequest", function () { left = total; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderAll();
    startSessionTimer();
  });
  document.body && document.body.addEventListener("htmx:afterSwap", function (e) { renderAll(e.target); });
})();
