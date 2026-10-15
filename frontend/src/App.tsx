import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getHealth } from './api';

const pages = ['Sources', 'Library', 'Organize', 'Preview'] as const;
type Page = typeof pages[number];
const copy: Record<Page, [string, string]> = {
  Sources: ['A fresh home for your music.', 'Bring your existing playlists and public links together. Keep every song’s story.'],
  Library: ['Every track. One catalogue.', 'Explore unique tracks while preserving every source playlist and repeated occurrence.'],
  Organize: ['Make room for a better collection.', 'Build local playlist plans using selected tracks and simple rules.'],
  Preview: ['See every change before it happens.', 'Review creations and updates before explicitly applying a plan to Spotify.'],
};

export function App() {
  const [page, setPage] = useState<Page>('Sources');
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, retry: false });
  return <div className="shell">
    <aside><a className="brand" href="/">◉ <span>Spotify<br/>Consolidator</span></a>
      <p className="eyebrow">YOUR WORKSPACE</p>
      <nav aria-label="Primary">{pages.map((item, i) => <button key={item}
        aria-current={page === item ? 'page' : undefined} onClick={() => setPage(item)}>
        <span className="step">0{i + 1}</span>{item}<span className="arrow">↗</span></button>)}</nav>
      <div className="local"><span className="dot"/> Local-first workspace<br/><small>Your plans stay yours.</small></div>
    </aside>
    <main><header><span>WORKSPACE / {page.toUpperCase()}</span><span className="badge">Foundation · v0.1</span></header>
      <section className="intro"><p className="eyebrow">YOUR MUSIC, RECONSIDERED</p><h1>{copy[page][0]}</h1><p>{copy[page][1]}</p></section>
      {page === 'Sources' ? <div className="cards"><section className="card"><div className="card-icon">↗</div>
        <h2>Destination account</h2><p>Connect the account where your new playlists will live. An empty account is welcome.</p>
        <span className="tag">OAuth connection coming next</span></section>
        <section className="card"><div className="card-icon">＋</div><h2>Public playlists</h2>
        <p>Import playlist links from across Spotify. Overlapping songs will share one catalogue entry.</p>
        <span className="tag">Import available after reader integration</span></section></div>
        : <section className="card empty"><h2>{page === 'Library' ? 'Your catalogue starts with your sources' : page === 'Organize' ? 'A plan before a playlist' : 'You’re in control'}</h2>
          <p>This view is part of the next implementation milestones. No Spotify changes can be made in this foundation build.</p>
          <button className="secondary" onClick={() => setPage('Sources')}>Back to sources →</button></section>}
      <section className="status" aria-live="polite"><div><strong>{health.isPending ? 'Checking backend…' : health.isError ? 'Backend unavailable' : 'Workspace backend is running'}</strong>
        <p>{health.isError ? health.error.message : 'Foundation build · Authentication, imports, and playlist writes are not enabled yet.'}</p></div>
        <button className="secondary" disabled={health.isFetching} onClick={() => void health.refetch()}>Check connection</button></section>
      <footer><span>Import → Organize → Preview → Apply</span><span>Nothing changes on Spotify without your approval.</span></footer>
    </main>
  </div>;
}
