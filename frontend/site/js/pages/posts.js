import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import { bindFilters, filterBar, fmtMoney, parseBadge, salaryRange, sectionHead, variableScopeText } from '../components.js';
import { drawer, emptyState, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { q: '', channelId: '', city: '', salaryStatus: '', salaryPeriod: '', variableScope: '' };

function openPost(post) {
  const pkg = post.salary_package || {};
  const variableItems = (pkg.variable_items || [])
    .map((item) => `<div class="row"><span>${esc(item.label || '浮动收入')}</span><b class="mono">${item.quantified ? '已量化计入' : '未量化，不计数'}</b></div>`)
    .join('');
  drawer({
    title: `${post.company_raw} · ${post.title_raw}`,
    subtitle: `${post.channel_name || post.channel_code} · ${post.external_id} · ${post.city}`,
    body: `${kv([
      ['薪资原值', `<b class="mono">${esc(post.salary_raw)}</b>`],
      ['口径状态', parseBadge(post)],
      ['计算周期', esc(post.salary_period_label || post.salary_period || '—')],
      ['发薪月数', `<span class="mono">${post.months}${pkg.months_explicit ? '' : '（缺省）'}</span>`],
      ['固定月薪', `<span class="tabular">${salaryRange(post.monthly_low, post.monthly_high)}</span>`],
      ['浮动月薪', pkg.variable_monthly_low === null || pkg.variable_monthly_low === undefined ? '未量化' : `<span class="tabular">${salaryRange(pkg.variable_monthly_low, pkg.variable_monthly_high)}</span>`],
      ['含浮动月薪', pkg.total_monthly_low === null || pkg.total_monthly_low === undefined ? '—' : `<span class="tabular">${salaryRange(pkg.total_monthly_low, pkg.total_monthly_high)}</span>`],
      ['可比月薪（排序口径）', `<b class="tabular">${salaryRange(post.comparable_monthly_low, post.comparable_monthly_high)}</b>`],
      ['可比中位', `<b class="tabular">${fmtMoney(post.comparable_monthly_median)}</b>`],
      ['是否含浮动', post.has_variable ? `是（${esc(variableScopeText(post.variable_scope))}）` : '否'],
      ['口径置信度', `<span class="mono">${Number(post.salary_confidence).toFixed(2)}</span>`],
      ['学历 / 经验', `${esc(post.degree_label)} · ${esc(post.experience_label)}`],
      ['发布时间', fmtTime(post.published_at)],
      ['过期时间', fmtTime(post.expire_at)],
      ['公司归一键', `<span class="mono">${esc(post.company_norm)}</span>`],
      ['职位词干', `<span class="mono">${esc(post.title_stem)}</span>`],
    ])}
    ${variableItems ? `<h3 style="margin:12px 0 6px;font-size:0.98rem">浮动项目</h3><div class="ledger">${variableItems}</div>` : ''}
    <h3 style="margin:12px 0 6px;font-size:0.98rem">换算过程</h3>
    <pre class="code">${esc((pkg.basis_steps || [post.salary_basis]).filter(Boolean).join('\n') || '—')}</pre>
    <h3 style="margin:12px 0 6px;font-size:0.98rem">原始岗位文本</h3>
    <pre class="code">${esc(post.raw_text || '—')}</pre>`,
  });
}

function previewBlock(result) {
  if (!result) {
    return '<div class="panel-note">输入一个薪资原值，点「试算」后由后端算法返回口径，不在浏览器里计算。</div>';
  }
  return `${kv([
    ['口径状态', parseBadge(result)],
    ['计算周期', esc(result.period_label || result.period || '—')],
    ['发薪月数', `<span class="mono">${result.months}${result.months_explicit ? '' : '（缺省）'}</span>`],
    ['固定月薪', salaryRange(result.fixed_monthly_low, result.fixed_monthly_high)],
    ['浮动月薪', result.variable_monthly_low === null || result.variable_monthly_low === undefined ? '未量化' : salaryRange(result.variable_monthly_low, result.variable_monthly_high)],
    ['含浮动月薪', result.total_monthly_low === null || result.total_monthly_low === undefined ? '—' : salaryRange(result.total_monthly_low, result.total_monthly_high)],
    ['可比月薪中位', `<b class="tabular">${fmtMoney(result.comparable_monthly_median)}</b>`],
    ['是否含浮动', result.has_variable ? `是（${esc(result.variable_scope_label || variableScopeText(result.variable_scope))}）` : '否'],
    ['置信度', `<span class="mono">${Number(result.confidence).toFixed(2)}</span>`],
  ])}
  <pre class="code" style="margin-top:10px">${esc((result.basis_steps || [result.norm_basis]).filter(Boolean).join('\n'))}</pre>`;
}

export const postsPage = {
  async render(view, ctx) {
    const render = () => postsPage.render(view, ctx);
    let posts;
    let channels;
    let samples;
    try {
      [posts, channels, samples] = await Promise.all([
        api.get('/api/posts', {
          q: state.q,
          channel_id: state.channelId,
          city: state.city,
          salary_status: state.salaryStatus,
          salary_period: state.salaryPeriod,
          variable_scope: state.variableScope,
          limit: 60,
        }),
        api.get('/api/channels'),
        api.get('/api/salary/samples'),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', render);
      return;
    }
    const cities = Array.from(new Set(posts.items.map((item) => item.city))).sort();

    view.innerHTML = `
      <div class="workbench">
        <section class="panel">
          ${sectionHead('03', '原始岗位 · 薪资原值对照', `${posts.total} 条 · 当前显示 ${posts.items.length} 条`)}
          <div class="panel-body">
            ${filterBar({
              fields: [
                { label: '搜索', name: 'q', value: state.q, placeholder: '职位 / 公司 / 外部ID', grow: true },
                {
                  label: '渠道',
                  name: 'channel_id',
                  value: state.channelId,
                  options: [{ value: '', label: '全部' }, ...channels.items.map((item) => ({ value: item.id, label: item.name }))],
                },
                {
                  label: '城市',
                  name: 'city',
                  value: state.city,
                  options: [{ value: '', label: '全部' }, ...cities.map((city) => ({ value: city, label: city }))],
                },
                {
                  label: '口径状态',
                  name: 'salary_status',
                  value: state.salaryStatus,
                  options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.parseStatus).map(([value, label]) => ({ value, label }))],
                },
                {
                  label: '计算周期',
                  name: 'salary_period',
                  value: state.salaryPeriod,
                  options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.payPeriod).map(([value, label]) => ({ value, label }))],
                },
                {
                  label: '浮动收入',
                  name: 'variable_scope',
                  value: state.variableScope,
                  options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.variableScope).map(([value, label]) => ({ value, label }))],
                },
              ],
              actions: can(ctx.user.role, 'export:read')
                ? '<button class="btn sm ghost" id="export-posts">导出岗位口径 CSV</button>'
                : '',
            })}
          </div>
          ${
            posts.items.length
              ? table({
                  rows: posts.items,
                  columns: [
                    {
                      key: 'title_raw',
                      label: '职位 / 公司',
                      render: (row) =>
                        `<b>${esc(row.title_raw)}</b><div class="cell-sub">${esc(row.company_raw)} · ${esc(row.channel_code)}</div>`,
                    },
                    { key: 'city', label: '城市', className: 'tight' },
                    {
                      key: 'salary_raw',
                      label: '薪资原值 / 周期',
                      className: 'mono',
                      render: (row) => `${esc(row.salary_raw)}<div class="cell-sub">${esc(ENUMS.payPeriod[row.salary_period] || row.salary_period || '—')} · ${esc(row.months)} 薪</div>`,
                    },
                    {
                      key: 'monthly_low',
                      label: '固定月薪',
                      className: 'num',
                      render: (row) => salaryRange(row.monthly_low, row.monthly_high),
                    },
                    {
                      key: 'has_variable',
                      label: '浮动',
                      className: 'tight',
                      render: (row) => (row.has_variable ? esc(variableScopeText(row.variable_scope)) : '<span class="muted">无</span>'),
                    },
                    {
                      key: 'comparable_monthly_median',
                      label: '可比中位',
                      className: 'num',
                      render: (row) => fmtMoney(row.comparable_monthly_median),
                    },
                    { key: 'salary_status', label: '口径', render: (row) => parseBadge(row) },
                    { key: 'published_at', label: '发布', className: 'tight', render: (row) => fmtTime(row.published_at) },
                  ],
                })
              : emptyState({ title: '这个筛选下没有原始岗位', hint: '换个渠道或口径状态再看。' })
          }
          <div class="panel-note">点击任一行查看归一说明与原始文本；「归一后月薪」由后端算法 A 计算，前端只做格式化。</div>
        </section>

        <div class="side-stack">
          <section class="panel">
            ${sectionHead('A', '薪资口径试算', 'services/salary_norm.py')}
            <div class="panel-body">
              <form id="salary-form" class="coupon-form">
                ${field({ label: '薪资原值', name: 'raw', value: '8-12K·13薪', placeholder: '如：年薪18万 / 4000-6000元/月 / 面议' })}
                <button class="btn accent" type="submit">试算口径</button>
              </form>
              <div id="salary-preview" style="margin-top:10px">${previewBlock(null)}</div>
            </div>
          </section>
          <section class="panel">
            ${sectionHead('B', '口径速查', '6 类常见写法')}
            <div class="panel-body ledger">
              ${samples.items
                .map(
                  (item) =>
                    `<div class="row"><span class="mono">${esc(item.raw)}</span><b>${item.monthly_median === null ? '不可比' : fmtMoney(item.monthly_median)}</b></div>`,
                )
                .join('')}
            </div>
            <div class="panel-note">以上中位由 <span class="mono">GET /api/salary/samples</span> 实时返回；月薪按 × 12 ÷ 发薪月数折算，年薪先 ÷ 12，日薪按 21.75 工作日/月折算；提成、年终奖单独标注是否量化，面议与矛盾区间进不可比清单。</div>
          </section>
        </div>
      </div>`;

    bindFilters(view, (values) => {
      state.q = values.q || '';
      state.channelId = values.channel_id || '';
      state.city = values.city || '';
      state.salaryStatus = values.salary_status || '';
      state.salaryPeriod = values.salary_period || '';
      state.variableScope = values.variable_scope || '';
      render();
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const post = posts.items.find((item) => String(item.id) === row.dataset.id);
        if (post) openPost(post);
      });
    });
    view.querySelector('#export-posts')?.addEventListener('click', async () => {
      try {
        await api.download('/api/exports/posts.csv', 'jobmerge-posts.csv');
        toast('岗位口径 CSV 已开始下载');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
    view.querySelector('#salary-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.target;
      const raw = form.raw.value.trim();
      const target = view.querySelector('#salary-preview');
      if (!raw) {
        target.innerHTML = '<div class="error-box">请输入薪资原值</div>';
        return;
      }
      const button = form.querySelector('button[type=submit]');
      button.disabled = true;
      try {
        const result = await api.post('/api/salary/normalize', { raw });
        target.innerHTML = previewBlock(result);
      } catch (err) {
        target.innerHTML = `<div class="error-box">${esc(errorMessage(err))}</div>`;
      } finally {
        button.disabled = false;
      }
    });
  },
};

export default postsPage;
