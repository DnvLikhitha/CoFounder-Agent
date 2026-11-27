import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 })
const rows = (value) => Array.isArray(value) ? value : []
const present = (value) => value != null && value !== '' &&
  (typeof value !== 'object' || Object.keys(value).length > 0)
const record = (value) => value && typeof value === 'object' && !Array.isArray(value)
const text = (value) => typeof value === 'string' ? value.trim() : ''
const label = (key) => key.replaceAll('_', ' ').replace(/^[a-z]/, (letter) => letter.toUpperCase())
const money = (value) => Number.isFinite(value) ? currency.format(value) : value
const suffix = (unit, formatter = number.format) =>
  (value) => Number.isFinite(value) ? formatter(value) + unit : value

const layouts = {
  problem_refined: [
    'problem_refined', 'target_user', 'pain_intensity', 'opportunity_statement',
    'existing_solutions', 'why_existing_solutions_fail', 'problem_tags',
  ],
  startup_idea: [
    'startup_name', 'tagline', 'one_liner', 'value_proposition', 'target_customer',
    'key_differentiator', 'unfair_advantage', 'business_type', 'rejected_ideas',
  ],
  market_research: [
    ['tam_usd_billions', 'Total addressable market (TAM)', suffix(' billion', money)],
    ['sam_usd_billions', 'Serviceable available market (SAM)', suffix(' billion', money)],
    ['som_usd_millions', 'Serviceable obtainable market (SOM)', suffix(' million', money)],
    ['cagr_percent', 'Compound annual growth rate (CAGR)', suffix('%')],
    'audience', 'findings', 'market_maturity', 'market_timing', 'target_segments',
    'market_trends', 'key_market_drivers', 'regulatory_environment',
  ],
  product_design: [
    ['must_have_features', 'Must-have features'], 'should_have_features', 'nice_to_have_features',
    ['core_ux_flows', 'User flows'], 'core_screens', 'design_principles',
    'design_system_recommendation', 'accessibility_notes',
  ],
  mvp_roadmap: [
    ['total_weeks', 'Total weeks'], 'first_user_milestone', ['sprints', 'Sprint plan'],
    'mvp_success_criteria',
  ],
  business_model: [
    'model', 'revenue_streams', ['gtm_phases', 'Go-to-market phases'], 'cost_structure',
    'customer_acquisition_strategy', 'key_partnerships', 'key_activities', 'value_delivered_to_customer',
  ],
  tech_architecture: [
    'architecture_pattern', 'architecture_description', 'frontend_stack', 'backend_stack',
    'database', ['ai_layer', 'AI layer'], 'infrastructure', 'component_interactions',
    'scalability_notes', ['estimated_monthly_infra_cost_usd', 'Estimated monthly infrastructure cost', money],
  ],
  security_compliance: [
    ['auth_recommendation', 'Authentication recommendations'],
    ['owasp_top10_checklist', 'OWASP Top 10 checklist'], 'security_checklist', 'compliance_requirements',
    'data_privacy_actions', ['llm_safety_measures', 'LLM safety measures'], 'security_launch_checklist',
  ],
  executive_summary: [
    ['executive_summary', 'Summary'], ['summary', 'Summary'], 'mission_statement',
    'one_liner', 'key_metrics_snapshot', 'elevator_pitch', 'investor_email_subject',
  ],
}

export function ArtifactContent({ reference, content }) {
  if (!present(content)) return <p className="muted">This artifact has no content.</p>
  if (reference.media_type === 'text/markdown') {
    return <div className="markdown-content"><Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown></div>
  }
  if (typeof content === 'string') return <p className="plain-content">{content}</p>
  const Specialized = Object.hasOwn(renderers, reference.kind) ? renderers[reference.kind] : null
  const layout = Object.hasOwn(layouts, reference.kind) ? layouts[reference.kind] : null
  const fields = layout ? selectedFields(content, layout) : []
  if (!Specialized && !fields.length) return <StructuredValue value={content} />
  return (
    <>
      {Specialized ? <Specialized data={content} /> : <Fields entries={fields} />}
      <details className="output-data">
        <summary>Full structured output</summary>
        <StructuredValue value={content} />
      </details>
    </>
  )
}

function selectedFields(data, fields) {
  return fields.map((field) => {
    const [key, title = label(key), format = (value) => value] = Array.isArray(field) ? field : [field]
    return [key, title, format(data?.[key])]
  }).filter(([, , value]) => present(value))
}

function Fields({ entries }) {
  return (
    <dl className="output-fields">
      {entries.map(([key, title, value]) => (
        <div key={key}><dt>{title}</dt><dd><StructuredValue value={value} /></dd></div>
      ))}
    </dl>
  )
}

function StructuredValue({ value }) {
  if (Array.isArray(value)) return value.length ? (
    <ul className="structured-list">{value.map((item, index) => <li key={index}><StructuredValue value={item} /></li>)}</ul>
  ) : <span className="muted">No entries supplied</span>
  if (!present(value)) return <span className="muted">Not supplied</span>
  if (record(value)) return <Fields entries={Object.entries(value).map(([key, item]) => [key, label(key), item])} />
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'string') return <span className="plain-content">{value}</span>
  return typeof value === 'number' ? number.format(value) : String(value)
}

function Dataset({ title, data, columns }) {
  const items = rows(data).filter(record)
  const visible = columns.filter(([key]) => items.some((item) => present(item[key])))
  if (!visible.length) return <p className="muted">{title} not supplied.</p>
  return (
    <div className="output-table" role="region" aria-label={title} tabIndex={0}>
      <table>
        <caption>{title}</caption>
        <thead><tr>{visible.map(([key, name]) => <th key={key} scope="col">{name}</th>)}</tr></thead>
        <tbody>{items.map((item, index) => (
          <tr key={index}>{visible.map(([key, , format = (value) => value], column) => {
            const Cell = column === 0 ? 'th' : 'td'
            return <Cell key={key} scope={column === 0 ? 'row' : undefined}><StructuredValue value={format(item[key])} /></Cell>
          })}</tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function Competitors({ data }) {
  return <>
    <Dataset title="Competitor comparison" data={data.competitors} columns={[
      ['name', 'Competitor'], ['market_position', 'Position'], ['starting_price_monthly', 'Starting monthly price', money],
      ['funding_stage', 'Funding stage'], ['strengths', 'Strengths'], ['weaknesses', 'Weaknesses'],
    ]} />
    <Fields entries={selectedFields(data, ['market_gaps', 'our_competitive_advantages', 'threat_level', 'competitive_moat_recommendation'])} />
  </>
}

function Personas({ data }) {
  const profiles = rows(Array.isArray(data) ? data : data.personas).filter(record)
  if (!profiles.length) return <p className="muted">No persona profiles were supplied.</p>
  return profiles.map((item, index) => (
    <section className="output-entry" key={index}>
      <h5>{text(item.name) || text(item.job_title) || `Persona ${index + 1}`}</h5>
      {text(item.quote) && <blockquote>{item.quote}</blockquote>}
      <Fields entries={selectedFields(item, ['job_title', 'location', 'pain_points', 'goals', 'current_tools_used',
        'buying_triggers', 'buying_blockers', ['willingness_to_pay_monthly_usd', 'Monthly willingness to pay', money]])} />
    </section>
  ))
}

function Pricing({ data }) {
  const tiers = rows(data.tiers).filter(record).map((tier) => ({ ...tier, tier_name: tier.tier_name ?? tier.name }))
  return <>
    <Dataset title="Pricing tiers" data={tiers} columns={[
      ['tier_name', 'Tier'], ['price_monthly_usd', 'Monthly', money], ['price_annual_usd', 'Annual', money],
      ['target_persona', 'Target'], ['features_included', 'Includes'], ['usage_limits', 'Usage limits'],
    ]} />
    <Fields entries={selectedFields(data, ['pricing_philosophy', 'pricing_rationale', 'freemium_conversion_strategy',
      ['annual_discount_percent', 'Annual discount', suffix('%')], 'enterprise_pricing_note'])} />
  </>
}

const series = [
  ['mrr_usd', 'Monthly recurring revenue'], ['net_profit_usd', 'Net profit'],
]

function Financials({ data }) {
  const projections = rows(data.monthly_projections)
    .filter(record).map((row) => ({ ...row, month: row.month ?? row.month_name }))
  return <>
    <Fields entries={selectedFields(data, [
      ['breakeven_month', 'Break-even month'], ['arr_month_12_usd', 'Month 12 annual recurring revenue', money],
      ['ltv_usd', 'Lifetime value', money], ['cac_usd', 'Customer acquisition cost', money],
      ['ltv_cac_ratio', 'Lifetime value to acquisition cost', suffix('×')],
      ['total_12mo_revenue_usd', '12-month revenue', money], ['total_12mo_costs_usd', '12-month costs', money],
    ])} />
    <ProjectionChart projections={projections} />
    <Dataset title="Monthly projections" data={projections} columns={[
      ['month', 'Month'], ['total_customers', 'Customers'], ['mrr_usd', 'Recurring revenue', money],
      ['revenue_usd', 'Revenue', money], ['total_costs_usd', 'Costs', money], ['net_profit_usd', 'Net profit', money],
      ['cumulative_loss_usd', 'Cumulative loss', money],
    ]} />
    <Fields entries={selectedFields(data, ['sensitivity_top_factors'])} />
  </>
}

function ProjectionChart({ projections }) {
  const samples = projections.filter((row) => (text(row.month) || Number.isFinite(row.month)) &&
    series.some(([key]) => Number.isFinite(row[key])))
  if (!samples.length) return <p className="muted">No monthly revenue or profit values were supplied for the chart.</p>
  const values = samples.flatMap((row) => series.map(([key]) => row[key])).filter(Number.isFinite)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  // Scale endpoints independently to keep the range finite even for unusually large inputs.
  const magnitude = Math.max(Math.abs(min), Math.abs(max), 1)
  const range = (max / magnitude - min / magnitude) || 1
  const percent = (value) => (value / magnitude - min / magnitude) * 100 / range
  const zero = percent(0)
  return (
    <figure className="projection-chart">
      <figcaption>Revenue and net profit by month (USD)</figcaption>
      <p className="muted">Exact values and missing months are shown in the table below.</p>
      {samples.map((row, index) => (
        <div className="chart-month" key={index} aria-hidden="true">
          <span>{row.month}</span>
          {series.filter(([key]) => Number.isFinite(row[key])).map(([key, title]) => (
            <div className="chart-series" key={key} title={`${title}: ${money(row[key])}`}>
              <span>{key === 'mrr_usd' ? 'MRR' : 'Profit'}</span>
              <div className="chart-track" style={{ '--zero': `${zero}%` }}>
                <span className={`chart-bar ${key === 'net_profit_usd' ? 'profit' : ''}`} style={{
                  '--start': `${Math.min(zero, percent(row[key]))}%`,
                  '--width': `${Math.abs(percent(row[key]) - zero)}%`,
                }} />
              </div>
              <span>{money(row[key])}</span>
            </div>
          ))}
        </div>
      ))}
    </figure>
  )
}

function Risks({ data }) {
  return <>
    <Fields entries={selectedFields(data, ['risk_summary', 'top_3_critical_risks'])} />
    <Dataset title="Risk register" data={data.risks} columns={[
      ['title', 'Risk'], ['category', 'Category'], ['probability', 'Probability'], ['impact', 'Impact'],
      ['risk_score', 'Score'], ['mitigation_strategy', 'Mitigation'], ['early_warning_signals', 'Early warnings'],
    ]} />
  </>
}

function Database({ data }) {
  const sql = [data.sql_schema, data.raw_sql].find((value) => typeof value === 'string' && present(value))
  return <>
    <Fields entries={selectedFields(data, ['entities', 'relationships', 'indexes_created', 'rls_policies_notes', 'backup_strategy'])} />
    <h5>SQL schema</h5>
    {sql ? <pre className="sql-preview"><code>{sql}</code></pre> : <p className="muted">No SQL schema was supplied.</p>}
  </>
}

function PitchDeck({ data }) {
  const slides = rows(Array.isArray(data) ? data : data.slides).filter(record).map((slide, index) => ({ slide, index }))
    .sort((a, b) => {
      const order = (item) => Number.isFinite(item.slide.slide_number) ? item.slide.slide_number : Infinity
      return order(a) - order(b) || a.index - b.index
    })
  const [page, setPage] = useState(0)
  if (!slides.length) return <p className="muted">No pitch deck slides were supplied.</p>
  const { slide } = slides[page]
  const title = text(slide.title) || text(slide.headline) ||
    `Slide ${Number.isFinite(slide.slide_number) ? slide.slide_number : page + 1}`
  return (
    <section className="deck-preview" aria-label="Pitch deck preview">
      <header className="section-heading">
        <h5>Pitch deck preview</h5>
        <span aria-live="polite">Slide {page + 1} of {slides.length}</span>
      </header>
      <div className="deck-slide">
        <h5>{title}</h5>
        {text(slide.headline) && slide.headline !== title && <p>{slide.headline}</p>}
        {present(slide.bullet_points) && <StructuredValue value={slide.bullet_points} />}
        {present(slide.key_stat) && <p className="score"><StructuredValue value={slide.key_stat} /></p>}
      </div>
      <div className="actions deck-actions">
        <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous slide</button>
        <button type="button" disabled={page === slides.length - 1} onClick={() => setPage(page + 1)}>Next slide</button>
      </div>
      {present(slide.speaker_notes) && <details><summary>Speaker notes</summary><StructuredValue value={slide.speaker_notes} /></details>}
    </section>
  )
}

const renderers = {
  competitor_analysis: Competitors,
  customer_personas: Personas,
  pricing_strategy: Pricing,
  financial_projections: Financials,
  risk_register: Risks,
  database_schema: Database,
  pitch_deck: PitchDeck,
}
