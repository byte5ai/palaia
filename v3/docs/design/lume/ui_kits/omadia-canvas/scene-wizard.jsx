/* Scene: Wizard — Walkthrough 3 (sales proposal).
   Step bar (donut glow on current) + label-left form + back/next toolbar.
   Send button opens a confirmation modal. */

function WizardScene() {
  const [stepIdx, setStepIdx] = React.useState(2); // current step = "Pricing"
  const [modal, setModal] = React.useState(null);  // 'send' | 'sent' | null

  const steps = [
    { label: 'Customer',  status: 'done' },
    { label: 'Use case',  status: 'done' },
    { label: 'Pricing',   status: 'current' },
    { label: 'Document',  status: 'upcoming' },
  ];

  return (
    <div className="condense" style={{
      position: 'relative', height: '100%',
      display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 260px',
      gap: 14, padding: '4px 0',
    }}>
      {/* Main pane */}
      <Pane raised style={{ padding: '24px 28px 18px' }}>
        {/* Header */}
        <div className="lume-caption" style={{
          color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 4,
        }}>Proposal · AcmeInsure · revision 3</div>
        <h1 className="lume-h1" style={{ margin: '0 0 22px' }}>Build a customer proposal</h1>

        {/* Step bar */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px', marginBottom: 24 }}>
          {steps.map((s, i) => (
            <React.Fragment key={s.label}>
              <StepDot status={s.status} label={s.label} />
              {i < steps.length - 1 && (
                <div style={{
                  flex: 1, height: 2, margin: '0 8px', alignSelf: 'center',
                  background: s.status === 'done'
                    ? 'var(--accent-fill)'
                    : s.status === 'current'
                      ? 'linear-gradient(90deg, var(--accent-fill) 0%, var(--border-subtle-btm) 100%)'
                      : 'var(--border-subtle-btm)',
                  boxShadow: s.status === 'done' ? '0 0 6px var(--accent-glow)' : 'none',
                  marginTop: 0,
                }} />
              )}
            </React.Fragment>
          ))}
        </div>

        {/* Form — Pricing step */}
        <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', rowGap: 14, columnGap: 18, alignItems: 'center' }}>
          <FieldLabel>Customer</FieldLabel>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Mono style={{ color: 'var(--text-primary)' }}>AcmeInsure</Mono>
            <span className="lume-body-sm" style={{ color: 'var(--state-warning-fg)' }}>· new contact</span>
          </div>

          <FieldLabel>Use case</FieldLabel>
          <div className="lume-body" style={{ color: 'var(--text-secondary)' }}>
            Insurance claims triage + automated damage assessment + escalation routing
          </div>

          <FieldLabel>Pricing tier</FieldLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <TierChoice
              tier="Starter"
              price="€2 400 / mo"
              detail="Up to 50 k claims · 1 region"
            />
            <TierChoice
              tier="Enterprise"
              price="€7 800 / mo"
              detail="Unlimited claims · 12-month evaluation period"
              selected
            />
            <TierChoice
              tier="Custom"
              price="—"
              detail="Negotiated · multi-region · dedicated SLA"
            />
          </div>

          <FieldLabel>Evaluation</FieldLabel>
          <input className="input" defaultValue="12 months · co-developed onboarding" style={{ maxWidth: 480 }} />

          <FieldLabel>Notes</FieldLabel>
          <textarea
            className="input"
            rows={2}
            defaultValue="Contract review wanted before proposal-send. Stefan in CC."
            style={{ resize: 'none', fontFamily: 'var(--font-sans)', lineHeight: '20px' }}
          />
        </div>

        {/* Footer toolbar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginTop: 22, paddingTop: 18,
          borderTop: '1px solid var(--border-subtle-btm)',
        }}>
          <span className="lume-body-sm" style={{ color: 'var(--text-tertiary)' }}>
            Autosaved · <Mono>14:23</Mono>
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="ghost">Back</Button>
            <Button variant="secondary" icon="file">Generate PDF</Button>
            <Button variant="signal" icon="arrow-up-right" onClick={() => setModal('send')}>
              Send to customer
            </Button>
          </div>
        </div>
      </Pane>

      {/* Side context pane */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Pane raised style={{ padding: '14px 16px' }}>
          <div className="lume-caption" style={{
            color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 10,
          }}>Earlier in this proposal</div>
          <Prose style={{ color: 'var(--text-secondary)', fontSize: 14, lineHeight: '22px' }}>
            AcmeInsure is a new contact — no record in CRM. Branch was pre-filled as <strong style={{ fontWeight: 600 }}>Insurance</strong>; pricing tiers were loaded from the standard Enterprise template.
          </Prose>
        </Pane>

        <Pane raised style={{ padding: '14px 16px' }}>
          <div className="lume-caption" style={{
            color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 8,
          }}>Recipient</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <Mono style={{ color: 'var(--text-primary)' }}>contact@acmeinsure.com</Mono>
            <span className="lume-body-sm" style={{ color: 'var(--text-tertiary)' }}>Sara Krenz · Head of Claims</span>
          </div>
        </Pane>

        <Pane raised style={{ padding: '14px 16px' }}>
          <div className="lume-caption" style={{
            color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 8,
          }}>External effect</div>
          <div className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>
            Sending the proposal triggers a confirmation modal. The email cannot be unsent.
          </div>
        </Pane>
      </div>

      {modal === 'send' && (
        <div className="modal-scrim" onClick={() => setModal(null)}>
          <div className="modal-pane" onClick={(e) => e.stopPropagation()}>
            <h2 className="lume-h2" style={{ margin: '0 0 6px' }}>Send proposal to contact@acmeinsure.com?</h2>
            <Prose style={{ color: 'var(--text-secondary)', margin: '0 0 18px' }}>
              This email cannot be unsent. The attached PDF is the version at <Mono style={{ color: 'inherit', fontSize: 14 }}>14:23</Mono>.
            </Prose>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Button variant="ghost" onClick={() => setModal(null)}>Cancel</Button>
              <Button variant="signal" icon="arrow-up-right" onClick={() => setModal('sent')}>Send</Button>
            </div>
          </div>
        </div>
      )}

      {modal === 'sent' && (
        <div className="modal-scrim" onClick={() => setModal(null)}>
          <div className="modal-pane" onClick={(e) => e.stopPropagation()}>
            <h2 className="lume-h2" style={{ margin: '0 0 6px' }}>Sent.</h2>
            <Prose style={{ color: 'var(--text-secondary)', margin: '0 0 18px' }}>
              Proposal delivered to <Mono style={{ color: 'inherit', fontSize: 14 }}>contact@acmeinsure.com</Mono> at <Mono style={{ color: 'inherit', fontSize: 14 }}>14:25</Mono>. The status appears in the canvas timeline.
            </Prose>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button variant="primary" onClick={() => setModal(null)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function FieldLabel({ children }) {
  return (
    <span className="lume-body-sm" style={{
      color: 'var(--text-secondary)',
      textAlign: 'right',
      paddingRight: 4,
    }}>{children}</span>
  );
}

function StepDot({ status, label }) {
  if (status === 'current') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, position: 'relative', flexShrink: 0 }}>
        <div style={{
          width: 22, height: 22, borderRadius: '50%',
          border: '2px solid var(--accent-fill)',
          background:
            'radial-gradient(circle, var(--accent-subtle) 0%, var(--accent-subtle) 35%, var(--accent-glow-core) 75%, transparent 100%)',
          boxShadow: '0 0 12px var(--accent-glow-core), 0 0 22px -4px var(--accent-glow-strong)',
        }} />
        <span className="lume-caption" style={{ color: 'var(--text-primary)', fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</span>
      </div>
    );
  }
  if (status === 'done') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, flexShrink: 0 }}>
        <div style={{
          width: 18, height: 18, borderRadius: '50%',
          background: 'var(--accent-fill)',
          display: 'grid', placeItems: 'center', color: '#fff',
          boxShadow: '0 0 6px var(--accent-glow)',
        }}>
          <Icon name="check" size={11} strokeWidth={3} />
        </div>
        <span className="lume-caption" style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{label}</span>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, flexShrink: 0 }}>
      <div style={{
        width: 18, height: 18, borderRadius: '50%',
        background: 'linear-gradient(180deg, var(--bg-surface-raised-top), var(--bg-surface-raised-btm))',
        border: '1px solid var(--border-subtle-btm)',
        borderTopColor: 'var(--border-subtle-top)',
      }} />
      <span className="lume-caption" style={{ color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>{label}</span>
    </div>
  );
}

function TierChoice({ tier, price, detail, selected }) {
  return (
    <label style={{
      display: 'grid', gridTemplateColumns: '20px 1fr auto', alignItems: 'center', gap: 12,
      padding: '10px 14px',
      borderRadius: 'var(--radius-md)',
      border: selected ? '1px solid var(--accent-fill)' : '1px solid var(--border-subtle-btm)',
      borderTopColor: selected ? 'var(--accent-fill)' : 'var(--border-subtle-top)',
      background: selected
        ? 'linear-gradient(180deg, var(--accent-subtle), var(--accent-subtle))'
        : 'linear-gradient(180deg, var(--bg-surface-raised-top), var(--bg-surface-raised-btm))',
      boxShadow: selected
        ? '0 0 0 4px var(--accent-glow), 0 0 12px var(--accent-glow-core), 0 1px 0 var(--top-edge-highlight) inset'
        : '0 1px 0 var(--top-edge-highlight) inset',
      cursor: 'pointer',
      minWidth: 0,
    }}>
      <span style={{
        width: 14, height: 14, borderRadius: '50%',
        border: selected ? '1px solid var(--accent-fill)' : '1px solid var(--border-strong-btm)',
        background: selected
          ? 'radial-gradient(circle, var(--accent-fill) 0 3px, transparent 4px)'
          : '#fff',
        boxShadow: selected ? '0 0 3px var(--accent-glow-core), 0 0 6px var(--accent-glow)' : 'none',
        flexShrink: 0,
      }} />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
        <span className="lume-body" style={{ fontWeight: 600, flexShrink: 0 }}>{tier}</span>
        <span className="lume-body-sm" style={{
          color: 'var(--text-tertiary)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{detail}</span>
      </div>
      <Mono style={{
        color: selected ? 'var(--accent-fill)' : 'var(--text-secondary)',
        fontWeight: selected ? 600 : 450,
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}>
        {price}
      </Mono>
    </label>
  );
}

window.WizardScene = WizardScene;
