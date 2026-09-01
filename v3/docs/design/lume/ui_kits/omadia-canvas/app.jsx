/* App root — switches between the four idiom scenes.
   The scene picker (top-right) is demo chrome, not part of Omadia UI. */

const SCENES = [
  { key: 'empty',     label: 'empty',     title: 'Empty canvas' },
  { key: 'spotlight', label: 'spotlight', title: 'Spotlight idiom' },
  { key: 'dashboard', label: 'dashboard', title: 'Dashboard idiom' },
  { key: 'workspace', label: 'workspace', title: 'Photoshop-workspace idiom' },
  { key: 'wizard',    label: 'wizard',    title: 'Wizard idiom' },
];

function App() {
  const [scene, setScene] = React.useState('dashboard');
  const [prompt, setPrompt] = React.useState('');

  // ⌘K opens spotlight
  React.useEffect(() => {
    const h = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setScene('spotlight');
      } else if (e.key === 'Escape' && scene === 'spotlight') {
        setScene('dashboard');
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [scene]);

  // Status text per scene
  const statusText = (() => {
    if (scene === 'workspace') {
      return (<>
        <span style={{ color: 'var(--state-warning-fg)' }}>● </span>
        editor session ·
        <span style={{ marginLeft: 6 }}>untitled-1284.png · 12 connectors live</span>
      </>);
    }
    if (scene === 'wizard') {
      return (<>
        <span className="live-dot" />
        proposal · AcmeInsure · autosaved 14:23
      </>);
    }
    return null; // default
  })();

  return (
    <>
      <CanvasFrame
        prompt={prompt}
        onPromptChange={setPrompt}
        onSpotlight={() => setScene('spotlight')}
        statusText={statusText}
        hidePrompt={scene === 'spotlight'}
      >
        {scene === 'empty'     && <EmptyScene />}
        {scene === 'dashboard' && <DashboardScene />}
        {scene === 'workspace' && <WorkspaceScene />}
        {scene === 'wizard'    && <WizardScene />}
      </CanvasFrame>

      {scene === 'spotlight' && (
        <Spotlight
          onClose={() => setScene('dashboard')}
          onPick={(r) => {
            // map spotlight result kind to a scene
            const kind = r.kind || '';
            if (kind.includes('editor'))  setScene('workspace');
            else if (kind === 'wizard')   setScene('wizard');
            else                          setScene('dashboard');
          }}
        />
      )}

      <ScenePicker scene={scene} setScene={setScene} />
    </>
  );
}

function ScenePicker({ scene, setScene }) {
  return (
    <div className="scene-picker" aria-label="Demo scene picker">
      {SCENES.map((s) => (
        <button
          key={s.key}
          className={scene === s.key ? 'active' : ''}
          onClick={() => setScene(s.key)}
          title={s.title}
        >{s.label}</button>
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
