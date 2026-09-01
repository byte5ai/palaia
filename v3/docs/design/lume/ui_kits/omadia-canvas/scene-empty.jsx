/* Scene: empty canvas + Spotlight overlay.
   Walkthrough 1, step 0 — before the user has asked anything. */

function EmptyScene({ onSpotlight }) {
  return (
    <div style={{
      position: 'absolute', inset: 0,
      display: 'grid', placeItems: 'center',
      padding: '0 0 140px',
    }}>
      <div style={{
        textAlign: 'center',
      }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 450,
          color: 'var(--text-tertiary)', letterSpacing: '0.04em',
          textTransform: 'uppercase', marginBottom: 8,
        }}>
          empty canvas
        </div>
        <div className="lume-body" style={{ color: 'var(--text-tertiary)' }}>
          Canvas ready. <Mono style={{ color: 'var(--text-secondary)' }}>⌘K</Mono> to start.
        </div>
      </div>
    </div>
  );
}

function Spotlight({ onPick, onClose }) {
  const [query, setQuery] = React.useState('show open jira tickets by ow');
  const [focused, setFocused] = React.useState(0);

  const results = [
    { icon: 'users',    label: 'Show open Jira tickets grouped by owner', kind: 'jira·hr' },
    { icon: 'database', label: 'ERP — remaining hour budget per person',  kind: 'erp' },
    { icon: 'image',    label: 'Edit a photo — crop, blur, retouch',      kind: 'editor' },
    { icon: 'file',     label: 'Draft a proposal for a new customer',     kind: 'wizard' },
    { icon: 'folder',   label: 'reports / q3-summary.pdf',                kind: 'recent' },
  ];

  React.useEffect(() => {
    const h = (e) => {
      if (e.key === 'Escape') onClose && onClose();
      if (e.key === 'ArrowDown') setFocused((f) => Math.min(f + 1, results.length - 1));
      if (e.key === 'ArrowUp')   setFocused((f) => Math.max(f - 1, 0));
      if (e.key === 'Enter')     onPick && onPick(results[focused]);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [focused, onPick, onClose, results]);

  return (
    <div className="spotlight-stage" onClick={onClose}>
      <div className="spotlight-card" onClick={(e) => e.stopPropagation()}>
        <div className="spotlight-input">
          <Icon name="search" size={20} strokeWidth={1.75} style={{ color: 'var(--text-tertiary)' }} />
          <input
            autoFocus
            placeholder="Ask anything…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span className="lume-mono-sm" style={{ color: 'var(--text-tertiary)' }}>⌘↩ to send</span>
        </div>

        <div className="spotlight-results">
          {results.map((r, i) => (
            <div
              key={r.label}
              className={'spotlight-result' + (i === focused ? ' focused' : '')}
              onMouseEnter={() => setFocused(i)}
              onClick={() => onPick && onPick(r)}
            >
              <span className="icon-wrap"><Icon name={r.icon} size={16} strokeWidth={1.75} /></span>
              <span className="label">{r.label}</span>
              <span className="kind">{r.kind}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { EmptyScene, Spotlight });
