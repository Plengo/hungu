# HUNGU Mobile Interface

> React component (`App`) powering the HUNGU mobile web UI, built with React hooks and styled with Tailwind CSS.

---

## Overview

The interface provides three core views:

| View | Description |
|------|-------------|
| `feed` | Main news feed sorted by hyper-local priority |
| `detail` | Full article with impact analysis and scriptural perspective |
| `profile` | User location settings and feed priority configuration |

---

## Key Features

- **Hyper-Local Prioritization** — News sorted by proximity: `Suburb → City → Province → Country`
- **Read for Me** — One-tap audio narration of the news feed
- **Impact Cards** — AI-generated "what this means for you" summaries per article
- **Scriptural Perspective** — Each article paired with a relevant Bible verse
- **Conflict Zone Badges** — Visual indicators for high-urgency war/conflict stories

---

## Component Structure

```
App
├── <header>          — Sticky top bar with logo and navigation buttons
├── <main>
│   ├── feed view     — Priority-sorted news cards with thumbnails
│   ├── detail view   — Full article, impact card, scriptural block, and context
│   └── profile view  — User suburb/city feed priority display
└── <nav>             — Fixed bottom navigation (Feed | Global | Me)
```

---

## Location Tier Priority

| Tier | Priority | Example |
|------|----------|---------|
| `Suburb` | 1 — Highest | Menlyn water maintenance |
| `City` | 2 | Pretoria infrastructure news |
| `Province` | 3 | Gauteng tax adjustments |
| `Country` | 4 | South Africa national news |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `react` | UI framework |
| `lucide-react` | Icon library |
| `tailwindcss` | Utility-first CSS styling |

---

## Source Code

```jsx
# HUNGU Mobile Interface

> React component (`App`) powering the HUNGU mobile web UI, built with React hooks and styled with Tailwind CSS.

---

## Overview

The interface provides three core views:

| View | Description |
|------|-------------|
| `feed` | Main news feed sorted by hyper-local priority |
| `detail` | Full article with impact analysis and scriptural perspective |
| `profile` | User location settings and feed priority configuration |

---

## Key Features

- **Hyper-Local Prioritization** — News sorted by proximity: `Suburb → City → Province → Country`
- **Read for Me** — One-tap audio narration of the news feed
- **Impact Cards** — AI-generated "what this means for you" summaries per article
- **Scriptural Perspective** — Each article paired with a relevant Bible verse
- **Conflict Zone Badges** — Visual indicators for high-urgency war/conflict stories

---

## Component Structure

```
App
├── <header>          — Sticky top bar with logo and navigation buttons
├── <main>
│   ├── feed view     — Priority-sorted news cards with thumbnails
│   ├── detail view   — Full article, impact card, scriptural block, and context
│   └── profile view  — User suburb/city feed priority display
└── <nav>             — Fixed bottom navigation (Feed | Global | Me)
```

---

## Location Tier Priority

| Tier | Priority | Example |
|------|----------|---------|
| `Suburb` | 1 — Highest | Menlyn water maintenance |
| `City` | 2 | Pretoria infrastructure news |
| `Province` | 3 | Gauteng tax adjustments |
| `Country` | 4 | South Africa national news |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `react` | UI framework |
| `lucide-react` | Icon library |
| `tailwindcss` | Utility-first CSS styling |

---

## Source Code

```jsx
import React, { useState, useMemo } from 'react';
import { 
  Home, 
  Search, 
  Menu, 
  PlayCircle, 
  MessageSquare, 
  MapPin, 
  ShieldCheck, 
  ChevronRight,
  User,
  Volume2,
  X,
  Send,
  BookOpen,
  Globe,
  Flame,
  Navigation
} from 'lucide-react';

// Enhanced Mock Data with Location Tiers for Prioritization
const MOCK_NEWS = [
  {
    id: 1,
    source: "Global Conflict Monitor",
    title: "Escalation in Northern Borders: Security Alert",
    summary: "New military movements have been reported, signaling a significant shift in regional stability.",
    fullContext: "Regional tensions have reached a boiling point as multi-national forces mobilize...",
    image: "https://images.unsplash.com/photo-1517021897933-0e0319cfbc28?auto=format&fit=crop&w=800&q=80",
    date: "45 mins ago",
    impact: "Energy costs in South Africa may rise by 15% due to shipping route closures.",
    category: "Wars",
    locationTier: "Country", // Level 4
    locationName: "South Africa",
    prophecy: {
      verse: "Matthew 24:7",
      summary: "For nation will rise against nation...",
      insight: "This conflict is a reminder of 'critical times'..."
    }
  },
  {
    id: 2,
    source: "Gauteng Provincial Gazette",
    title: "New Provincial Tax Adjustments",
    summary: "The Provincial government has announced adjustments to vehicle licensing fees.",
    fullContext: "Starting next month, vehicle license renewals in Gauteng will see a 5% increase...",
    image: "https://images.unsplash.com/photo-1554224155-1696413565d3?auto=format&fit=crop&w=800&q=80",
    date: "2 hours ago",
    impact: "Your annual car registration will increase by R75.",
    category: "Economy",
    locationTier: "Province", // Level 3
    locationName: "Gauteng",
    prophecy: {
      verse: "James 5:4",
      summary: "Look! The wages you kept back... keep crying out.",
      insight: "Economic pressures often highlight the need for justice."
    }
  },
  {
    id: 3,
    source: "Pretoria Local News",
    title: "Menlyn Suburb Water Maintenance",
    summary: "Scheduled water maintenance will affect several streets in Menlyn this weekend.",
    fullContext: "Maintenance teams will be working on the main pipe lines on Atterbury Road...",
    image: "https://images.unsplash.com/photo-1542013936693-884638332954?auto=format&fit=crop&w=800&q=80",
    date: "10 mins ago",
    impact: "Your house in Menlyn will have no water from 08:00 to 16:00 on Saturday.",
    category: "Local",
    locationTier: "Suburb", // Level 1 (Highest Priority)
    locationName: "Menlyn",
    prophecy: {
      verse: "Isaiah 41:17",
      summary: "The afflicted and the poor are seeking water...",
      insight: "Infrastructure challenges remind us of the promise of a world where needs are perfectly met."
    }
  }
];

const App = () => {
  const [view, setView] = useState('feed'); 
  const [selectedNews, setSelectedNews] = useState(null);
  const [isReading, setIsReading] = useState(false);
  const [user, setUser] = useState({
    name: 'User',
    suburb: 'Menlyn',
    city: 'Pretoria',
    province: 'Gauteng',
    country: 'South Africa'
  });

  // Prioritization Logic: Suburb -> City -> Province -> Country
  const prioritizedNews = useMemo(() => {
    return [...MOCK_NEWS].sort((a, b) => {
      const tiers = { Suburb: 1, City: 2, Province: 3, Country: 4 };
      return tiers[a.locationTier] - tiers[b.locationTier];
    });
  }, []);

  const handleNewsClick = (news) => {
    setSelectedNews(news);
    setView('detail');
  };

  const toggleRead = (e) => {
    e.stopPropagation();
    setIsReading(!isReading);
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans flex flex-col max-w-md mx-auto shadow-2xl overflow-hidden relative border-x border-slate-200">
      
      <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-lg border-b border-slate-100 p-4 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-black rounded-lg flex items-center justify-center">
            <ShieldCheck className="text-white w-5 h-5" />
          </div>
          <h1 className="text-xl font-black italic tracking-tighter uppercase">HUNGU</h1>
        </div>
        <div className="flex gap-4 items-center">
          <button onClick={() => setView('feed')}><Navigation className="w-5 h-5 text-blue-600" /></button>
          <button onClick={() => setView('profile')}><User className="w-5 h-5 text-slate-600" /></button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto pb-24">
        {view === 'feed' && (
          <div className="p-4 space-y-6">
            <div className="bg-slate-900 rounded-[2.5rem] p-6 text-white shadow-2xl relative overflow-hidden">
              <div className="relative z-10">
                <p className="text-blue-400 text-xs font-bold uppercase tracking-widest mb-1">
                  Hyper-Local Focus: {user.suburb}
                </p>
                <h2 className="text-2xl font-bold mb-4">Priority Updates.</h2>
                <p className="text-slate-300 text-sm leading-relaxed mb-6">
                  Showing critical news for <strong>{user.suburb}</strong> first, followed by {user.city} and global events.
                </p>
                <button 
                  onClick={toggleRead}
                  className="w-full bg-white text-black py-4 rounded-2xl flex items-center justify-center gap-3 font-bold shadow-lg"
                >
                  {isReading ? <Volume2 className="animate-pulse" /> : <PlayCircle className="fill-black" />}
                  {isReading ? "Reading your news..." : "Read my news"}
                </button>
              </div>
            </div>

            <div className="space-y-10">
              {prioritizedNews.map((news) => (
                <div key={news.id} className="group cursor-pointer" onClick={() => handleNewsClick(news)}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-black uppercase tracking-tighter px-2 py-0.5 rounded ${news.locationTier === 'Suburb' ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-700'}`}>
                        {news.locationName}
                      </span>
                      <span className="text-[10px] text-slate-400 font-bold">{news.date}</span>
                    </div>
                    {news.locationTier === 'Suburb' && (
                      <span className="text-[10px] font-bold text-blue-600 flex items-center gap-1 animate-pulse">
                        <MapPin className="w-3 h-3" /> Priority
                      </span>
                    )}
                  </div>
                  
                  <div className="relative aspect-video rounded-[2rem] overflow-hidden mb-4 shadow-sm transition-all">
                    <img src={news.image} alt={news.title} className="w-full h-full object-cover" />
                    {news.category === 'Wars' && (
                      <div className="absolute top-4 left-4 bg-red-600 text-white px-3 py-1 rounded-full text-[10px] font-bold flex items-center gap-1">
                        <Flame className="w-3 h-3" /> Conflict Zone
                      </div>
                    )}
                  </div>

                  <h3 className="text-xl font-bold leading-tight mb-2 pr-4">{news.title}</h3>
                  <p className="text-slate-500 text-sm line-clamp-2 leading-relaxed">
                    {news.summary}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {view === 'detail' && selectedNews && (
          <div className="animate-in slide-in-from-right duration-300 pb-20">
            <div className="sticky top-16 z-40 bg-white/80 backdrop-blur-md p-4 flex items-center justify-between border-b border-slate-100">
              <button onClick={() => setView('feed')} className="text-sm font-bold text-slate-500 flex items-center gap-1">
                <X className="w-4 h-4" /> Close
              </button>
              <button onClick={toggleRead} className="bg-black text-white px-4 py-2 rounded-full text-xs font-bold flex items-center gap-2">
                <Volume2 className="w-4 h-4" /> Listen
              </button>
            </div>

            <img src={selectedNews.image} className="w-full h-64 object-cover" alt="Detail" />
            
            <div className="p-6">
              <h2 className="text-3xl font-black mb-6 leading-[1.1] tracking-tight">{selectedNews.title}</h2>
              
              <div className="bg-blue-600 text-white p-6 rounded-[2rem] shadow-xl mb-6">
                <h4 className="text-xs font-black uppercase tracking-widest text-blue-200 mb-2 flex items-center gap-2">
                  <MapPin className="w-3 h-3" /> Impact: {selectedNews.locationName}
                </h4>
                <p className="text-lg font-bold leading-snug">{selectedNews.impact}</p>
              </div>

              <div className="bg-amber-50 border border-amber-200 p-6 rounded-[2rem] mb-8">
                <h4 className="text-xs font-black uppercase tracking-widest text-amber-700 mb-3 flex items-center gap-2">
                  <BookOpen className="w-4 h-4" /> Scriptural Perspective
                </h4>
                <blockquote className="text-xl font-serif italic text-amber-900 mb-3 leading-tight">
                  "{selectedNews.prophecy.verse}: {selectedNews.prophecy.summary}"
                </blockquote>
                <p className="text-sm text-amber-800 leading-relaxed font-medium">
                  {selectedNews.prophecy.insight}
                </p>
              </div>

              <div className="space-y-6">
                <p className="text-slate-800 leading-relaxed text-lg">
                  {selectedNews.fullContext}
                </p>
              </div>
            </div>
          </div>
        )}

        {view === 'profile' && (
          <div className="p-6">
             <h2 className="text-3xl font-black italic mb-8 uppercase">Profile</h2>
             <div className="space-y-4">
               <div className="p-6 bg-white rounded-[2rem] border border-slate-200 shadow-sm">
                 <label className="text-[10px] font-black text-slate-400 block mb-1 uppercase tracking-widest">Feed Priority</label>
                 <p className="font-bold text-slate-800 text-xl">{user.suburb}, {user.city}</p>
                 <p className="text-xs text-blue-600 font-bold mt-2">Adjusting hierarchy...</p>
               </div>
             </div>
          </div>
        )}
      </main>

      <nav className="fixed bottom-0 left-0 right-0 max-w-md mx-auto bg-white/90 backdrop-blur-md border-t border-slate-100 flex justify-around p-4 pb-8 shadow-2xl">
        <button onClick={() => setView('feed')} className={`flex flex-col items-center gap-1 ${view === 'feed' ? 'text-black' : 'text-slate-300'}`}>
          <Home className="w-6 h-6" />
          <span className="text-[8px] font-black uppercase tracking-widest">Feed</span>
        </button>
        <button className="flex flex-col items-center gap-1 text-slate-300">
          <Globe className="w-6 h-6" />
          <span className="text-[8px] font-black uppercase tracking-widest">Global</span>
        </button>
        <button onClick={() => setView('profile')} className={`flex flex-col items-center gap-1 ${view === 'profile' ? 'text-black' : 'text-slate-300'}`}>
          <User className="w-6 h-6" />
          <span className="text-[8px] font-black uppercase tracking-widest">Me</span>
        </button>
      </nav>
    </div>
  );
};

export default App;
```

```
