/* Omadia UI kit — small reusable primitives.
   Exported to window so other Babel files can use them. */

const { useState, useEffect, useRef, useMemo } = React;

// ---------- Icon (Lucide via lucide.dev CDN, fed by static SVG paths) ----------
function Icon({ name, size = 16, strokeWidth = 1.75, style }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      dangerouslySetInnerHTML={{ __html: window.LUCIDE_PATHS[name] || '' }}
    />
  );
}

// ---------- Button ----------
function Button({ variant = 'secondary', icon, children, onClick, disabled, style }) {
  const cls = `btn btn-${variant}` + (disabled ? ' is-disabled' : '');
  return (
    <button className={cls} onClick={disabled ? undefined : onClick} style={style} disabled={disabled}>
      {icon ? <Icon name={icon} size={14} strokeWidth={2} /> : null}
      {children}
    </button>
  );
}

// ---------- Pane ----------
function Pane({ raised, children, style, className = '' }) {
  return (
    <div className={(raised ? 'pane-raised' : 'pane') + ' ' + className} style={style}>
      {children}
    </div>
  );
}

// ---------- List row ----------
function ListRow({ selected, onClick, children, style }) {
  return (
    <div
      className={'list-row' + (selected ? ' selected' : '')}
      onClick={onClick}
      style={style}
    >
      {children}
    </div>
  );
}

// ---------- Mono / Prose helpers ----------
const Mono  = ({ children, style }) => <span className="lume-mono" style={style}>{children}</span>;
const MonoSm = ({ children, style }) => <span className="lume-mono-sm" style={style}>{children}</span>;
const Prose = ({ children, style }) => <div className="lume-prose" style={style}>{children}</div>;

// ---------- Status dot — text-only semantic state ----------
function StatusDot({ kind = 'success', children, style }) {
  const color = {
    success: 'var(--state-success-fg)',
    warning: 'var(--state-warning-fg)',
    error:   'var(--state-error-fg)',
    info:    'var(--text-tertiary)',
  }[kind];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color, ...style }}>
      <span style={{
        display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
        background: color, boxShadow: `0 0 6px ${color}`,
      }} />
      <span className="lume-body-sm">{children}</span>
    </span>
  );
}

// ---------- Skeleton block ----------
function Skel({ w = '100%', h = 12, style, r }) {
  return <div className="skeleton" style={{ width: w, height: h, borderRadius: r || 4, ...style }} />;
}

// ---------- KPI tile ----------
function KPI({ label, value, delta, deltaKind = 'success', unit, style }) {
  const deltaColor = deltaKind === 'success' ? 'var(--state-success-fg)' : 'var(--state-error-fg)';
  return (
    <div className="pane-raised" style={{ padding: '12px 14px 14px', ...style }}>
      <div className="lume-caption" style={{
        color: 'var(--text-tertiary)', letterSpacing: '0.04em',
        textTransform: 'uppercase', marginBottom: 6,
        whiteSpace: 'nowrap',
      }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span className="lume-mono" style={{
          fontSize: 24, lineHeight: '28px', fontWeight: 500,
          color: 'var(--text-primary)',
          fontFeatureSettings: '"tnum"',
        }}>{value}</span>
        {unit ? <span className="lume-body-sm" style={{ color: 'var(--text-tertiary)' }}>{unit}</span> : null}
      </div>
      {delta != null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 4,
          color: deltaColor,
          textShadow: `0 0 6px ${deltaColor}33`,
        }}>
          <Icon name={deltaKind === 'success' ? 'trending-up' : 'trending-down'} size={12} strokeWidth={2.2} />
          <span className="lume-mono-sm" style={{ color: deltaColor }}>{delta}</span>
        </div>
      )}
    </div>
  );
}

// ---------- Toolbar (horizontal) ----------
function Toolbar({ children, style, align = 'right' }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: align === 'right' ? 'flex-end' : align === 'between' ? 'space-between' : 'flex-start',
      gap: 8,
      ...style,
    }}>{children}</div>
  );
}

Object.assign(window, {
  Icon, Button, Pane, ListRow, Mono, MonoSm, Prose,
  StatusDot, Skel, KPI, Toolbar,
});
