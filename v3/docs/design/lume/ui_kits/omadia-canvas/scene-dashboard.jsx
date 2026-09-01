/* Scene: Dashboard — Walkthrough 1 (Jira × ERP × HR comparison).
   The agent has materialised a heading + prose + table with highlighted rows. */

function DashboardScene() {
  // Bernd is the "active selection" — the row the agent is operating on.
  // Anna + Cara are passive highlights (the agent flagged them, but they're
  // not the current operation target).
  const [selected, setSelected] = React.useState('bernd');
  const [showVacation, setShowVacation] = React.useState(true);

  const rows = [
    { id: 'anna',    person: 'Anna Reuter',     tickets: 14, story: 31, budget: 6.2,  flagged: true,  out: 'Fri' },
    { id: 'bernd',   person: 'Bernd Maier',     tickets: 9,  story: 18, budget: 4.5,  flagged: true,  out: '—' },
    { id: 'cara',    person: 'Cara Ohanian',    tickets: 11, story: 24, budget: 7.0,  flagged: true,  out: 'Wed–Fri' },
    { id: 'derek',   person: 'Derek Yoon',      tickets: 6,  story: 12, budget: 12.3, flagged: false, out: '—' },
    { id: 'elif',    person: 'Elif Sarac',      tickets: 17, story: 36, budget: 22.0, flagged: false, out: '—' },
    { id: 'frank',   person: 'Frank Holstein',  tickets: 4,  story: 9,  budget: 18.5, flagged: false, out: 'Mon' },
    { id: 'georgia', person: 'Georgia Lin',     tickets: 8,  story: 16, budget: 11.0, flagged: false, out: '—' },
  ];

  return (
    <div className="condense" style={{
      position: 'relative', height: '100%',
      display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px',
      gap: 16, padding: '4px 0 4px',
    }}>
      {/* ---- Main column ---- */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
        {/* Header */}
        <div>
          <div className="lume-caption" style={{
            color: 'var(--text-tertiary)', letterSpacing: '0.04em',
            textTransform: 'uppercase', marginBottom: 4,
          }}>
            Jira × ERP × HR · revision 5
          </div>
          <h1 className="lume-h1" style={{ margin: 0 }}>Open tickets vs. remaining budget</h1>
        </div>

        {/* Prose narration */}
        <Prose style={{ color: 'var(--text-primary)', maxWidth: 680 }}>
          Three people are under budget — <strong style={{ fontWeight: 600 }}>Anna, Bernd, Cara</strong>.
          {' '}Total <Mono style={{ color: 'var(--text-secondary)' }}>69</Mono> open tickets across the team;
          {' '}<Mono style={{ color: 'var(--text-secondary)' }}>15</Mono> story-points on the flagged rows.
        </Prose>

        {/* KPI strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          <KPI label="Open tickets"   value="69" delta="+8 this wk"  deltaKind="error" />
          <KPI label="Under budget"   value="3"  unit="people" delta="+1 vs. last wk" deltaKind="error" />
          <KPI label="Hours remaining" value="81.5" unit="h"  delta="−14h" deltaKind="error" />
          <KPI label="On vacation"    value="3"  unit="this week" />
        </div>

        {/* Table */}
        <Pane style={{ padding: 0 }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: showVacation
              ? '1.6fr 0.7fr 0.7fr 0.9fr 0.9fr'
              : '1.8fr 0.8fr 0.8fr 1.0fr',
            alignItems: 'center',
            padding: '12px 18px 8px',
            borderBottom: '1px solid var(--border-subtle-btm)',
            borderTopColor: 'var(--border-subtle-top)',
            background: 'linear-gradient(180deg, var(--bg-surface-top), var(--bg-surface-btm))',
          }}>
            <div className="lume-caption" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>Owner</div>
            <div className="lume-caption" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', textAlign: 'right' }}>Tickets</div>
            <div className="lume-caption" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', textAlign: 'right' }}>Story pts</div>
            <div className="lume-caption" style={{ color: 'var(--accent-fill)', letterSpacing: '0.04em', textTransform: 'uppercase', textAlign: 'right' }}>
              Hours left ↓
            </div>
            {showVacation && (
              <div className="lume-caption condense" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', textAlign: 'right' }}>Out</div>
            )}
          </div>

          {rows.map((r) => {
            const isSelected   = selected === r.id;
            const isHighlight  = r.flagged && !isSelected;
            const showLumeWash = isHighlight || isSelected;
            return (
              <div
                key={r.id}
                onClick={() => setSelected(r.id)}
                style={{
                  position: 'relative',
                  display: 'grid',
                  gridTemplateColumns: showVacation
                    ? '1.6fr 0.7fr 0.7fr 0.9fr 0.9fr'
                    : '1.8fr 0.8fr 0.8fr 1.0fr',
                  alignItems: 'center',
                  padding: '11px 18px',
                  margin: '2px 6px',
                  borderRadius: 6,
                  cursor: 'default',
                  // Passive highlight + active selection both get the
                  // subtle row tint and the top-edge accent.glow-core sliver.
                  background: showLumeWash
                    ? 'linear-gradient(180deg, var(--accent-subtle), rgba(31,143,163,0.04))'
                    : undefined,
                  boxShadow: showLumeWash
                    ? 'inset 0 1px 0 var(--accent-glow-core)'
                    : undefined,
                }}
              >
                {/* Active selection adds: 2px solid accent left bar + bright inner core spot at the leading edge */}
                {isSelected && (
                  <>
                    <span aria-hidden style={{
                      position: 'absolute',
                      left: 0, top: 0, bottom: 0,
                      width: 2,
                      background: 'var(--accent-fill)',
                      borderTopLeftRadius: 6,
                      borderBottomLeftRadius: 6,
                    }} />
                    <span aria-hidden style={{
                      position: 'absolute',
                      left: 2, top: '50%',
                      transform: 'translateY(-50%)',
                      width: 24, height: 24,
                      borderRadius: '50%',
                      background: 'radial-gradient(circle, var(--accent-glow-core) 0%, transparent 70%)',
                      pointerEvents: 'none',
                    }} />
                  </>
                )}
                <div className="lume-body" style={{ position: 'relative' }}>{r.person}</div>
                <div className="lume-mono" style={{ textAlign: 'right' }}>{r.tickets}</div>
                <div className="lume-mono" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>{r.story}</div>
                <div className="lume-mono" style={{
                  textAlign: 'right',
                  color: r.flagged ? 'var(--state-error-fg)' : 'var(--text-primary)',
                  fontWeight: r.flagged ? 600 : 450,
                }}>{r.budget.toFixed(1)} h</div>
                {showVacation && (
                  <div className="lume-mono" style={{
                    textAlign: 'right',
                    color: r.out === '—' ? 'var(--text-tertiary)' : 'var(--text-secondary)',
                  }}>{r.out}</div>
                )}
              </div>
            );
          })}
        </Pane>

        {/* Status row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingRight: 4 }}>
          <StatusDot kind="success">Patch applied. <Mono style={{ color: 'inherit' }}>treeRevision 5</Mono></StatusDot>
          <div style={{ display: 'flex', gap: 6 }}>
            <Button variant="ghost" icon="copy">Copy</Button>
            <Button variant="ghost" icon="external-link">Open in Jira</Button>
          </div>
        </div>
      </div>

      {/* ---- Right inspector / detail pane ---- */}
      <RightInspector selected={selected} rows={rows} />
    </div>
  );
}

function RightInspector({ selected, rows }) {
  const row = rows.find((r) => r.id === selected) || rows[0];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Pane raised style={{ padding: '14px 16px' }}>
        <div className="lume-caption" style={{
          color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 6,
        }}>Detail</div>
        <h2 className="lume-h2" style={{ margin: '0 0 10px' }}>{row.person}</h2>

        <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr', rowGap: 6, columnGap: 12 }}>
          <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Tickets</span>
          <Mono style={{ color: 'var(--text-primary)' }}>{row.tickets}</Mono>
          <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Story points</span>
          <Mono style={{ color: 'var(--text-primary)' }}>{row.story}</Mono>
          <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Hours left</span>
          <Mono style={{
            color: row.flagged ? 'var(--state-error-fg)' : 'var(--text-primary)',
            fontWeight: row.flagged ? 600 : 450,
          }}>{row.budget.toFixed(1)} h</Mono>
          <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Out</span>
          <Mono style={{ color: 'var(--text-primary)' }}>{row.out}</Mono>
        </div>
      </Pane>

      <Pane raised style={{ padding: '14px 16px' }}>
        <div className="lume-caption" style={{
          color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 8,
        }}>Recent tickets</div>
        {[
          ['OPS-1284', 'Migrate payments staging'],
          ['OPS-1276', 'Failed retry on webhook 502'],
          ['ENG-918',  'Refactor session mutex'],
        ].map(([id, title]) => (
          <div key={id} style={{ padding: '5px 0', display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Mono style={{ color: 'var(--accent-fill)', fontSize: 12 }}>{id}</Mono>
            <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>{title}</span>
          </div>
        ))}
      </Pane>

      <Pane raised style={{ padding: '14px 16px' }}>
        <div className="lume-caption" style={{
          color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 8,
        }}>Sub-agent calls</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            ['jira', '1.8 s'],
            ['erp',  '2.3 s'],
            ['hr',   '0.9 s'],
          ].map(([name, ms]) => (
            <div key={name} style={{
              display: 'grid',
              gridTemplateColumns: '8px 1fr auto',
              alignItems: 'center',
              gap: 8,
            }}>
              <span style={{
                display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
                background: 'var(--state-success-fg)',
                boxShadow: '0 0 6px var(--state-success-fg)',
              }} />
              <Mono style={{ color: 'var(--text-primary)' }}>{name}<span style={{ color: 'var(--text-tertiary)' }}>·sub-agent</span></Mono>
              <MonoSm style={{ color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>{ms}</MonoSm>
            </div>
          ))}
        </div>
      </Pane>
    </div>
  );
}

window.DashboardScene = DashboardScene;
