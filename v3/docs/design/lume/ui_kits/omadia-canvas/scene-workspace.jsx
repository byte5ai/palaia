/* Scene: Photoshop workspace — Walkthrough 2 (image edit).
   Sharp-cornered canvas-region · Lume material around it · donut-glow active tool */

function WorkspaceScene() {
  const [tool, setTool] = React.useState('brush');

  const tools = [
    ['move',         'Move'],
    ['hand',         'Hand'],
    ['square-dashed','Marquee select'],
    ['brush',        'Brush'],
    ['eraser',       'Eraser'],
    ['type',         'Text'],
    ['pen-tool',     'Pen'],
    ['pipette',      'Eyedropper'],
    ['zoom-in',      'Zoom'],
  ];

  return (
    <div className="condense" style={{
      position: 'relative', height: '100%',
      display: 'grid',
      gridTemplateColumns: '52px 1fr 300px',
      gap: 14, padding: '4px 0 8px',
    }}>
      {/* ---- Left tool rail ---- */}
      <div style={{
        background: 'linear-gradient(180deg, var(--bg-surface-sunken-top), var(--bg-surface-sunken-btm))',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-subtle-btm)',
        borderTopColor: 'var(--border-subtle-top)',
        padding: '8px 6px',
        display: 'flex', flexDirection: 'column', gap: 4,
        alignSelf: 'start',
      }}>
        {tools.map(([t, label]) => {
          const active = t === tool;
          return (
            <button
              key={t}
              onClick={() => setTool(t)}
              title={label}
              style={{
                position: 'relative',
                width: 40, height: 36,
                display: 'grid', placeItems: 'center',
                background: active
                  ? 'radial-gradient(circle at center, var(--accent-subtle) 0%, var(--accent-subtle) 35%, var(--accent-glow-core) 75%, transparent 100%)'
                  : 'transparent',
                border: active ? '1px solid var(--accent-fill)' : '1px solid transparent',
                borderRadius: 'var(--radius-editor)',
                color: active ? 'var(--accent-fill)' : 'var(--text-secondary)',
                cursor: 'pointer',
                boxShadow: active
                  ? '0 0 12px var(--accent-glow-core), 0 0 22px -4px var(--accent-glow-strong)'
                  : 'none',
                transition: 'all var(--duration-quick) var(--easing-standard)',
              }}
            >
              <Icon name={t} size={18} strokeWidth={1.75} />
            </button>
          );
        })}
        <div style={{ height: 1, background: 'var(--border-subtle-btm)', margin: '4px 4px' }} />
        <button
          title="Magic wand (Lucide stand-in for magic-wand)"
          style={{
            width: 40, height: 36, display: 'grid', placeItems: 'center',
            background: 'transparent', border: '1px solid transparent',
            borderRadius: 'var(--radius-editor)', color: 'var(--text-secondary)', cursor: 'pointer',
          }}
        >
          <Icon name="wand-sparkles" size={18} strokeWidth={1.75} />
        </button>
      </div>

      {/* ---- Center canvas-region (sharp corners, opaque, accent border + outer glow) ---- */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, whiteSpace: 'nowrap', overflow: 'hidden' }}>
            <span className="lume-body-sm" style={{ color: 'var(--text-tertiary)' }}>untitled-1284.png</span>
            <MonoSm style={{ color: 'var(--text-tertiary)' }}>1920 × 1080 · 16:9</MonoSm>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Button variant="ghost" icon="minus" />
            <MonoSm style={{ color: 'var(--text-secondary)' }}>100%</MonoSm>
            <Button variant="ghost" icon="plus" />
          </div>
        </div>

        <div style={{
          flex: 1,
          background: 'var(--bg-surface-sunken-btm)',
          border: '2px solid var(--accent-fill)',
          borderRadius: 'var(--radius-editor)',
          boxShadow: '0 0 0 1px var(--border-strong-btm), 0 0 20px var(--accent-glow)',
          padding: 18,
          display: 'grid', placeItems: 'center',
          minHeight: 320,
        }}>
          {/* Mock image — simulated photograph */}
          <div style={{
            position: 'relative',
            aspectRatio: '16 / 9',
            width: '100%',
            maxWidth: 720,
            background:
              'linear-gradient(180deg, #C9D7E2 0%, #E2D5B9 55%, #8A8E78 100%)',
            boxShadow: '0 8px 24px rgba(20,25,30,0.16)',
            overflow: 'hidden',
          }}>
            {/* Horizon highlight */}
            <div style={{ position: 'absolute', left: 0, right: 0, top: '55%', height: 1, background: 'rgba(0,0,0,0.18)' }} />
            {/* Foreground silhouette */}
            <div style={{
              position: 'absolute', left: 0, right: 0, bottom: 0, height: '38%',
              background: 'linear-gradient(180deg, transparent 0%, rgba(40,40,30,0.25) 80%, rgba(20,20,12,0.55) 100%)',
            }} />
            {/* Selection — marching ants box around the (removed) lamp area */}
            <div style={{
              position: 'absolute', right: '8%', top: '14%',
              width: '18%', height: '38%',
              border: '1.5px dashed var(--accent-fill)',
              boxShadow: '0 0 12px var(--accent-glow)',
            }} />
            <span style={{
              position: 'absolute', right: '8%', top: 'calc(14% - 18px)',
              fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-fill)',
              background: 'var(--bg-surface-raised-btm)', padding: '1px 6px', borderRadius: 4,
              border: '1px solid var(--accent-fill)',
            }}>selection · 312 × 410 px</span>
          </div>
        </div>

        {/* Status line below canvas */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <StatusDot kind="warning">
            <Mono style={{ color: 'inherit' }}>remove-object</Mono> · running (Tier&nbsp;3)
          </StatusDot>
          <MonoSm style={{ color: 'var(--text-tertiary)' }}>treeRevision 5 · last patch 2.1 s ago</MonoSm>
        </div>
      </div>

      {/* ---- Right inspector + layer-stack ---- */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
        <Pane raised style={{ padding: '12px 14px' }}>
          <div className="lume-caption" style={{
            color: 'var(--text-tertiary)', letterSpacing: '0.04em',
            textTransform: 'uppercase', marginBottom: 8,
          }}>Inspector · selection</div>

          <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr', alignItems: 'center', rowGap: 8, columnGap: 10 }}>
            <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Blur</span>
            <SliderRow value={4} max={20} suffix="px" />

            <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Feather</span>
            <SliderRow value={2} max={20} suffix="px" />

            <span className="lume-body-sm" style={{ color: 'var(--text-secondary)' }}>Opacity</span>
            <SliderRow value={85} max={100} suffix="%" />
          </div>

          <div style={{ display: 'flex', gap: 6, marginTop: 12, justifyContent: 'flex-end' }}>
            <Button variant="ghost">Reset</Button>
            <Button variant="primary">Apply</Button>
          </div>
        </Pane>

        <Pane raised style={{ padding: '12px 14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <div className="lume-caption" style={{
              color: 'var(--text-tertiary)', letterSpacing: '0.04em', textTransform: 'uppercase',
            }}>Layers</div>
            <Icon name="layers" size={14} style={{ color: 'var(--text-tertiary)' }} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <LayerRow icon="image" name="Background" badge="locked" />
            <LayerRow icon="square-dashed" name="Blur mask" badge="auto" selected />
            <LayerRow icon="sparkles" name="Lamp removal" badge="ai" />
            <LayerRow icon="type" name="Text · Q3 release" badge="hidden" muted />
          </div>
        </Pane>
      </div>
    </div>
  );
}

function SliderRow({ value, max, suffix }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        flex: 1, position: 'relative', height: 4, borderRadius: 999,
        background: 'linear-gradient(180deg, var(--bg-surface-sunken-top), var(--bg-surface-sunken-btm))',
        border: '1px solid var(--border-subtle-btm)',
        borderTopColor: 'var(--border-subtle-top)',
      }}>
        <div style={{
          position: 'absolute', left: 0, top: -1, bottom: -1, width: `${pct}%`,
          borderRadius: 999,
          background: 'linear-gradient(90deg, var(--accent-fill), var(--accent-fill-hover))',
          boxShadow: '0 0 6px var(--accent-glow), 0 0 12px var(--accent-glow-core)',
        }} />
        <div style={{
          position: 'absolute', left: `calc(${pct}% - 7px)`, top: -5,
          width: 14, height: 14, borderRadius: '50%',
          background: 'var(--accent-fill)',
          boxShadow: '0 0 0 1px var(--accent-fill-hover), 0 0 6px var(--accent-glow-core), 0 0 12px var(--accent-glow-strong)',
        }} />
      </div>
      <MonoSm style={{ color: 'var(--text-secondary)', minWidth: 38, textAlign: 'right' }}>
        {value}{suffix}
      </MonoSm>
    </div>
  );
}

function LayerRow({ icon, name, badge, selected, muted }) {
  return (
    <div className={'list-row' + (selected ? ' selected' : '')} style={{
      padding: '6px 10px',
      display: 'grid', gridTemplateColumns: '18px 1fr auto', alignItems: 'center', gap: 8,
      opacity: muted ? 0.55 : 1,
    }}>
      <Icon name={icon} size={14} style={{ color: 'var(--text-tertiary)' }} />
      <span className="lume-body-sm">{name}</span>
      <MonoSm style={{ color: 'var(--text-tertiary)' }}>{badge}</MonoSm>
    </div>
  );
}

window.WorkspaceScene = WorkspaceScene;
