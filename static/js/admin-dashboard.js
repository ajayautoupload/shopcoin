(() => {
  const dataElement = document.getElementById('admin-dashboard-data');
  if (!dataElement) return;
  const data = JSON.parse(dataElement.textContent);
  const svgNS = 'http://www.w3.org/2000/svg';
  const colors = ['#0ab39c', '#7b61d1'];

  function svgElement(tag, attributes = {}, label = '') {
    const element = document.createElementNS(svgNS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (label) element.textContent = label;
    return element;
  }

  function numberLabel(value) {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}m`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
    return Number(value || 0).toLocaleString();
  }

  function axes(svg, width, height, maxValue, labels, left = 38, bottom = 28) {
    const plotWidth = width - left - 8;
    const plotHeight = height - bottom - 8;
    for (let line = 0; line <= 4; line += 1) {
      const y = 8 + (plotHeight * line) / 4;
      svg.append(svgElement('line', {x1: left, x2: width - 5, y1: y, y2: y, class: 'chart-gridline'}));
      svg.append(svgElement('text', {x: left - 7, y: y + 3, 'text-anchor': 'end', class: 'chart-axis-label'}, numberLabel(maxValue * (4 - line) / 4)));
    }
    const count = labels.length;
    const step = Math.max(1, Math.ceil(count / 7));
    labels.forEach((label, index) => {
      if (index % step !== 0 && index !== count - 1) return;
      const x = left + (count <= 1 ? plotWidth / 2 : (plotWidth * index) / (count - 1));
      svg.append(svgElement('text', {x, y: height - 6, 'text-anchor': 'middle', class: 'chart-axis-label'}, String(label)));
    });
    return {left, bottom, plotWidth, plotHeight};
  }

  function drawLineChart(container, seriesList) {
    const width = Math.max(container.clientWidth, 280);
    const height = container.clientHeight || 190;
    const allPoints = seriesList.flatMap(series => series.values);
    const maxValue = Math.max(1, ...allPoints.map(point => Number(point.value) || 0));
    const labels = seriesList[0]?.values.map(point => point.label) || [];
    const svg = svgElement('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': container.getAttribute('aria-label') || 'Database activity chart'});
    const plot = axes(svg, width, height, maxValue, labels);
    seriesList.forEach((series, seriesIndex) => {
      const points = series.values;
      if (!points.length) return;
      const coords = points.map((point, index) => {
        const x = plot.left + (points.length <= 1 ? plot.plotWidth / 2 : (plot.plotWidth * index) / (points.length - 1));
        const y = 8 + plot.plotHeight - (plot.plotHeight * (Number(point.value) || 0)) / maxValue;
        return [x, y];
      });
      const path = coords.map(([x, y], index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' ');
      if (seriesIndex === 0) {
        const area = `${path} L ${coords[coords.length - 1][0]} ${8 + plot.plotHeight} L ${coords[0][0]} ${8 + plot.plotHeight} Z`;
        svg.append(svgElement('path', {d: area, class: 'chart-area'}));
      }
      svg.append(svgElement('path', {d: path, class: 'chart-line', style: `stroke:${colors[seriesIndex % colors.length]}`}));
      coords.forEach(([x, y], index) => {
        const point = svgElement('circle', {cx: x, cy: y, r: points.length > 50 ? 1.8 : 3, class: 'chart-dot', style: `stroke:${colors[seriesIndex % colors.length]}`} );
        point.append(svgElement('title', {}, `${points[index].label}: ${numberLabel(points[index].value)}`));
        svg.append(point);
      });
    });
    container.replaceChildren(svg);
  }

  function drawBarChart(container, points) {
    const width = Math.max(container.clientWidth, 280);
    const height = container.clientHeight || 220;
    const maxValue = Math.max(1, ...points.map(point => Number(point.value) || 0));
    const svg = svgElement('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': container.getAttribute('aria-label') || 'Database totals chart', 'data-no-translate': 'true'});
    const plot = axes(svg, width, height, maxValue, points.map(point => point.label), 45, 42);
    const slot = plot.plotWidth / Math.max(points.length, 1);
    points.forEach((point, index) => {
      const value = Number(point.value) || 0;
      const barHeight = (plot.plotHeight * value) / maxValue;
      const barWidth = Math.min(34, slot * .64);
      const x = plot.left + index * slot + (slot - barWidth) / 2;
      const y = 8 + plot.plotHeight - barHeight;
      const bar = svgElement('rect', {x, y, width: barWidth, height: Math.max(barHeight, 1), class: 'chart-bar'});
      bar.append(svgElement('title', {}, `${point.label}: ${numberLabel(value)}`));
      svg.append(bar);
    });
    container.replaceChildren(svg);
  }

  const chartDefinitions = {
    sales: () => drawLineChart(document.querySelector('[data-chart="sales"]'), [{values: data.sales || []}]),
    monthly: () => drawBarChart(document.querySelector('[data-chart="monthly"]'), data.monthly || []),
    registrations: () => {
      const target = document.querySelector('[data-chart="registrations"]');
      drawLineChart(target, [{values: data.customers || []}, {values: data.shopkeepers || []}]);
      const legend = document.createElement('div');
      legend.className = 'chart-legend-row';
      legend.innerHTML = '<span>Customers</span><span class="legend-secondary">Shopkeepers</span>';
      target.append(legend);
    },
    coins: () => {
      const target = document.querySelector('[data-chart="coins"]');
      drawLineChart(target, [{values: data.purchases || []}, {values: data.redemptions || []}]);
      const legend = document.createElement('div');
      legend.className = 'chart-legend-row';
      legend.innerHTML = '<span>Purchase coins</span><span class="legend-secondary">Redeemed coins</span>';
      target.append(legend);
    },
    engagement: () => drawLineChart(document.querySelector('[data-chart="engagement"]'), [{values: data.engagement || []}]),
    shops: () => drawBarChart(document.querySelector('[data-chart="shops"]'), data.shops || []),
  };

  Object.values(chartDefinitions).forEach(draw => draw());
  let resizeTimer;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => Object.values(chartDefinitions).forEach(draw => draw()), 120);
  });

  document.querySelectorAll('[data-table-search]').forEach(input => {
    input.addEventListener('input', () => {
      const table = document.getElementById(input.dataset.tableSearch);
      const term = input.value.trim().toLocaleLowerCase();
      table?.querySelectorAll('tbody tr').forEach(row => {
        row.hidden = Boolean(term) && !row.textContent.toLocaleLowerCase().includes(term);
      });
    });
  });

  const sidebar = document.getElementById('adminSidebar');
  const toggle = document.querySelector('.sidebar-toggle');
  const backdrop = document.querySelector('.sidebar-backdrop');
  function setSidebar(open) {
    sidebar?.classList.toggle('is-open', open);
    backdrop?.classList.toggle('is-visible', open);
    if (backdrop) backdrop.hidden = !open;
    toggle?.setAttribute('aria-expanded', String(open));
  }
  toggle?.addEventListener('click', () => setSidebar(!sidebar?.classList.contains('is-open')));
  backdrop?.addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setSidebar(false); });

  const period = document.getElementById('periodFilter');
  period?.addEventListener('change', () => {
    if (period.value !== 'custom') period.form?.requestSubmit();
  });
})();
