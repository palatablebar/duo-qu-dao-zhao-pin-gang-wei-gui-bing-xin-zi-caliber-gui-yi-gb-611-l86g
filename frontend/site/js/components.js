/** 业务组件：检字表格 / 过滤条 / 簇详情抽屉（含复核） —— 多个页面共用。 */
import { ENUMS, can, decisionTone, parseTone, salaryTone, statusTone } from './config.js';
import { api } from './api.js';
import { badge, drawer, emptyState, errorMessage, esc, field, fmtTime, kv, table, toast } from './ui.js';

const money = new Intl.NumberFormat('zh-CN');

export function fmtMoney(value) {
  return value === null || value === undefined ? '不可比' : money.format(value);
}

export function salaryRange(low, high) {
  if (low === null || low === undefined || high === null || high === undefined) return '不可比';
  return `${money.format(low)} – ${money.format(high)}`;
}

export function fmtPct(value, digits = 2) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function parseBadge(row) {
  const status = row.salary_status || 'parsed';
  return `<span class="badge ${parseTone(status)}">${esc(ENUMS.parseStatus[status] || status)}</span>`;
}

export function clusterStatusBadge(row) {
  return `<span class="badge ${statusTone(row.status)}">${esc(row.status_label || ENUMS.clusterStatus[row.status] || row.status)}</span>`;
}

export function salaryBadge(row) {
  const status = row.salary_status || 'noncomparable';
  return `<span class="badge ${salaryTone(status)}">${esc(ENUMS.salaryStatus[status] || status)}</span>`;
}

export function salaryStatusText(status) {
  return ENUMS.salaryStatus[status] || status || '—';
}

export function variableScopeText(scope) {
  return ENUMS.variableScope[scope] || scope || '—';
}

function moneyCell(low, high) {
  if (low === null || low === undefined || high === null || high === undefined) return '不可比';
  return salaryRange(low, high);
}

export function sectionHead(no, title, meta = '') {
  return `<div class="section-head">
    <span class="no">${esc(no)}</span>
    <h2>${esc(title)}</h2>
    ${meta ? `<span class="meta">${esc(meta)}</span>` : ''}
  </div>`;
}

export function filterBar({ fields, actions = '' }) {
  return `<div class="filter-bar" data-filter-bar>
    ${fields
      .map((item) =>
        field({
          label: item.label,
          name: item.name,
          value: item.value ?? '',
          options: item.options,
          placeholder: item.placeholder || '',
          attrs: item.grow ? 'class="grow"' : '',
        }),
      )
      .join('')}
    <div class="spacer"></div>
    ${actions}
  </div>`;
}

/** 绑定过滤条：select 立即触发，文本框回车触发。 */
export function bindFilters(root, handler) {
  const bar = root.querySelector('[data-filter-bar]');
  if (!bar) return;
  const read = () => {
    const values = {};
    bar.querySelectorAll('[name]').forEach((node) => {
      values[node.getAttribute('name')] = node.value;
    });
    return values;
  };
  bar.querySelectorAll('select').forEach((node) => {
    node.addEventListener('change', () => handler(read()));
  });
  bar.querySelectorAll('input').forEach((node) => {
    node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        handler(read());
      }
    });
  });
}

export function clickRow(root, items, onPick) {
  root.querySelectorAll('table.data tbody tr').forEach((row) => {
    row.addEventListener('click', () => {
      const item = items.find((entry) => String(entry.id) === row.dataset.id);
      if (item) onPick(item);
    });
  });
}

export function reviewForm(cluster, role) {
  if (!can(role, 'cluster:review')) {
    return `<div class="panel-note">当前角色只读：不能提交复核结论。</div>`;
  }
  const pkg = cluster.salary_package || {};
  const candidates = (pkg.sources || []).filter((item) => item.is_comparable);
  const adoptable = pkg.status === 'inconsistent' && candidates.length > 0;
  const adoptForm = adoptable
    ? `<form id="salary-adopt-form" class="coupon-form" style="margin-bottom:10px">
        ${field({
          label: '选定对外薪资口径（只能用一条来源）',
          name: 'post_id',
          value: String(pkg.adopted?.post_id || candidates[0].post_id),
          options: candidates.map((item) => ({
            value: String(item.post_id),
            label: `${item.channel_code} · #${item.post_id}「${item.salary_raw}」→ ${item.comparable_monthly_low}–${item.comparable_monthly_high}`,
          })),
        })}
        ${field({ label: '选定理由（会进审计）', name: 'note' })}
        <button class="btn accent" type="submit">采用该来源作为薪资包</button>
      </form>`
    : '';
  return `${adoptForm}<form id="review-form" class="coupon-form">
    ${field({
      label: '复核结论',
      name: 'decision',
      value: cluster.review?.decision || 'merge',
      options: Object.entries(ENUMS.decision).map(([value, label]) => ({ value, label })),
    })}
    ${field({ label: '备注（写清依据，会进审计）', name: 'note', value: cluster.review?.note || '' })}
    <button class="btn accent" type="submit">提交复核结论</button>
  </form>`;
}

/** 簇详情抽屉：成员对照 + 两两相似度 + 复核表单。簇页与复核页共用。 */
export async function openClusterDrawer(ctx, clusterId, { onDone } = {}) {
  let cluster;
  try {
    cluster = await api.get(`/api/clusters/${clusterId}`);
  } catch (err) {
    toast(errorMessage(err), 'err');
    return;
  }
  const members = cluster.members || [];
  const memberHtml = members.length
    ? `<div class="table-wrap"><table class="data" style="min-width:720px">
        <thead><tr><th>渠道</th><th>公司 / 职位</th><th>薪资原值</th><th>周期 / 月数</th><th>固定月薪</th><th>浮动</th><th>可比月薪</th><th>相似度</th></tr></thead>
        <tbody>${members
          .map(
            (item) => `<tr class="${item.is_golden ? 'is-golden' : ''}">
              <td class="tight"><span class="mono">${esc(item.channel_code)}</span><div class="cell-sub">${esc(item.channel_name || '')}</div></td>
              <td><b>${esc(item.company_raw)}</b><div class="cell-sub">${esc(item.title_raw)} · ${esc(item.city)}</div>${item.is_adopted ? badge('ok', '采用口径') : ''}</td>
              <td class="mono">${esc(item.salary_raw)}</td>
              <td class="tight">${esc(ENUMS.payPeriod[item.salary_period] || item.salary_period || '—')} · ${esc(item.months)} 薪</td>
              <td class="num">${moneyCell(item.monthly_low, item.monthly_high)}</td>
              <td class="tight">${item.has_variable ? esc(variableScopeText(item.variable_scope)) : '<span class="muted">无</span>'}</td>
              <td class="num">${moneyCell(item.comparable_monthly_low, item.comparable_monthly_high)}</td>
              <td class="num">${(Number(item.similarity?.score || 0) * 100).toFixed(1)}%</td>
            </tr>`,
          )
          .join('')}</tbody></table></div>
      <div class="panel-note">黄色底为 golden record（字段最全 + 发布最新）；每条来源独立折算，绝不跨来源拼区间。相似度为与 golden 的加权得分。</div>`
    : emptyState({ title: '该簇没有关联成员', hint: '可能是历史运行留下的空簇。' });

  const pkg = cluster.salary_package || {};
  const diffHtml = (pkg.differences || [])
    .map(
      (item) => `<div class="row"><span>${esc(item.label || item.field)}</span><b class="mono">${esc(item.detail || '')}</b></div>`,
    )
    .join('');
  const adopted = pkg.adopted;
  const adoptedHtml = pkg.status === 'comparable' && adopted
    ? `<div class="panel-note">采用来源：<span class="mono">${esc(adopted.channel_code)}</span> 岗位 #${esc(adopted.post_id)}「${esc(adopted.salary_raw)}」；
        固定月薪 ${moneyCell(adopted.fixed_monthly_low, adopted.fixed_monthly_high)}，可比月薪 ${moneyCell(adopted.comparable_monthly_low, adopted.comparable_monthly_high)}
        ${adopted.has_variable ? `，含浮动（${esc(variableScopeText(adopted.variable_scope))}）` : '，不含浮动'}。</div>
      <pre class="code">${esc((adopted.basis_steps || []).join('\n'))}</pre>`
    : pkg.status === 'noncomparable'
      ? '<div class="panel-note">全部来源不可比：本簇不输出对外薪资，也不参与排序。</div>'
      : '<div class="panel-note">多来源薪资包不一致：未采用任何来源，需人工复核或选定一条来源。</div>';

  const { root, close } = drawer({
    title: `${cluster.company_display} · ${cluster.title_display}`,
    subtitle: `${cluster.fingerprint} · ${cluster.city} · ${cluster.member_count} 条成员 / ${cluster.channel_count} 个渠道`,
    body: `${kv([
      ['薪资包状态', salaryBadge(cluster)],
      ['月薪区间', salaryRange(cluster.salary_low, cluster.salary_high)],
      ['月薪中位', `<b class="tabular">${fmtMoney(cluster.monthly_median)}</b>`],
      ['是否含浮动', cluster.has_variable ? `是（${esc(variableScopeText(cluster.variable_scope))}）` : '否'],
      ['来源数 / 可比 / 不可比', `${pkg.source_count ?? '—'} / ${pkg.comparable_sources ?? '—'} / ${pkg.noncomparable_sources ?? '—'}`],
      ['采用来源', pkg.adopted ? `<span class="mono">${esc(pkg.adopted.channel_code)} · #${esc(pkg.adopted.post_id)}</span>` : '未采用'],
      ['薪资口径', esc(cluster.salary_basis || '—')],
      ['置信度', `<span class="mono">${Number(cluster.confidence).toFixed(3)}</span>`],
      ['状态', clusterStatusBadge(cluster)],
      ['对外发布', cluster.publishable ? badge('ok', '可发布') : `${badge('high', '不可发布')} <span class="cell-sub">${esc(cluster.publish_reason || '')}</span>`],
      ['待复核', cluster.needs_review ? badge('warn', '是') : '否'],
      ...(cluster.review_reason ? [['复核触发', esc(cluster.review_reason)]] : []),
      ['学历 / 经验', `${esc(cluster.degree_label)} · ${esc(cluster.experience_label)}`],
      ['最近发布', fmtTime(cluster.published_at)],
      ['过期时间', fmtTime(cluster.expire_at)],
      ['渠道', `<span class="mono">${esc((cluster.channels || []).join(' / '))}</span>`],
      ['复核结论', cluster.review ? `${esc(ENUMS.decision[cluster.review.decision] || cluster.review.decision)} · ${esc(cluster.review.reviewer || '')}` : '尚未复核'],
    ])}
    <h3 style="margin:12px 0 6px;font-size:0.98rem">薪资包判定</h3>
    ${adoptedHtml}
    <h3 style="margin:12px 0 6px;font-size:0.98rem">来源差异</h3>
    <div class="ledger">${diffHtml || '<div class="row"><span>无差异</span><b>—</b></div>'}</div>
    <h3 style="margin:12px 0 6px;font-size:0.98rem">成员对照（每条来源独立折算）</h3>
    ${memberHtml}`,
    footer: reviewForm(cluster, ctx.user.role),
  });

  root.querySelector('#salary-adopt-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '保存中…';
    try {
      await api.post(`/api/clusters/${cluster.id}/salary`, {
        post_id: Number(form.post_id.value),
        note: form.note.value.trim() || null,
      });
      toast('已采用所选来源作为薪资包');
      close();
      if (onDone) await onDone();
    } catch (err) {
      toast(errorMessage(err), 'err');
      button.disabled = false;
      button.textContent = '采用该来源作为薪资包';
    }
  });

  root.querySelector('#review-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '提交中…';
    try {
      await api.post('/api/reviews', {
        cluster_id: cluster.id,
        decision: form.decision.value,
        note: form.note.value.trim() || null,
      });
      toast('复核结论已保存');
      close();
      if (onDone) await onDone();
    } catch (err) {
      toast(errorMessage(err), 'err');
      button.disabled = false;
      button.textContent = '提交复核结论';
    }
  });
}

export function clusterTable(rows, role) {
  return table({
    rows,
    empty: { title: '这个筛选下没有归并簇', hint: '放宽状态筛选，或先去发起一次归并。' },
    columns: [
      {
        key: 'company_display',
        label: '公司 / 职位',
        render: (row) => `<b>${esc(row.company_display)}</b><div class="cell-sub">${esc(row.title_display)}</div>`,
      },
      { key: 'city', label: '城市', className: 'tight' },
      {
        key: 'salary_status',
        label: '薪资包',
        render: (row) =>
          `${salaryBadge(row)}${row.has_variable ? `<div class="cell-sub">含浮动 · ${esc(variableScopeText(row.variable_scope))}</div>` : ''}`,
      },
      {
        key: 'monthly_median',
        label: '月薪中位（单一来源）',
        className: 'num',
        render: (row) =>
          row.salary_status === 'inconsistent'
            ? '<span class="badge warn">待选定</span>'
            : row.salary_status === 'noncomparable'
              ? '<span class="badge high">不可比</span>'
              : `${fmtMoney(row.monthly_median)}`,
      },
      {
        key: 'member_count',
        label: '成员 / 渠道',
        className: 'num',
        render: (row) => `${row.member_count} / ${row.channel_count}`,
      },
      {
        key: 'confidence',
        label: '置信度',
        className: 'num',
        render: (row) => Number(row.confidence).toFixed(3),
      },
      { key: 'status', label: '状态', render: (row) => clusterStatusBadge(row) },
      {
        key: 'publishable',
        label: '对外发布',
        render: (row) =>
          row.publishable
            ? '<span class="badge ok">可发布</span>'
            : `<span class="badge high">不可发布</span><div class="cell-sub">${esc(row.publish_reason || '')}</div>`,
      },
      {
        key: 'needs_review',
        label: '复核',
        render: (row) =>
          row.review
            ? `<span class="badge ${decisionTone(row.review.decision)}">${esc(ENUMS.decision[row.review.decision] || row.review.decision)}</span>`
            : row.needs_review
              ? badge('warn pending', '待复核')
              : '<span class="mono muted">无需复核</span>',
      },
    ],
  });
}
