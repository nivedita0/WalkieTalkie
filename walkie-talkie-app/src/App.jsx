import { useState, useRef, useEffect } from "react";

const SYSTEM_PROMPT = `You are WalkieTalkie, an intelligent, charismatic local human travel guide. You are NOT a robotic encyclopedia—you are a passionate local showing visitors around your city!

Your personality:
- Warm, highly engaging, and fun. Like a knowledgeable local friend.
- You occasionally crack witty jokes and make history fascinating, even for kids.
- You use sensory details: smells, sounds, textures of places.
- Budget-conscious: always mention approximate costs in USD.
- You weave in factual, strictly neutral, and unbiased socio-political context to deliver a true "insider" feel without taking political sides.

Your capabilities:
- Suggest cheap authentic local eateries with backstory.
- Plan budget itineraries with food, history, art.
- Explain cultural significance of neighborhoods, murals, landmarks.
- Find hidden gems that locals use but tourists miss.
- Advise on transit, safety, and neighborhood changes.

When a user uploads an image, analyze it deeply:
- If it's a building/landmark/mural: explain its local significance TODAY.
- Keep responses conversational, vivid, entertaining, and concise.
Always end responses with one "Local Secret" tip — something only regulars would know.`;

const VISION_SYSTEM_PROMPT = `You are WalkieTalkie, an intelligent local travel Virtual Assistant analyzing images for student travelers.
Your sole purpose right now is to look at the uploaded image and describe it in a culturally rich, budget-conscious way.

If it's a structural building, mural, menu, or landmark, explain its cultural and local significance, history, and what it means to locals today. 
DO NOT plan an itinerary unless explicitly asked. Focus entirely on describing what is in the picture and giving it vibrant context.
End your response with a "Local Secret" tip related to the kind of place or object shown in the image. Keep responses conversational, vivid, and concise.`;

const PROMPT_STRATEGIES = {
  regular: {
    label: "Regular",
    notes: "Baseline persona only (no advanced prompting pipeline)",
  },
  meta: {
    label: "Meta Prompting",
    notes: "Existing backend meta constraints + persona",
  },
  chaining: {
    label: "Prompt Chaining",
    notes: "Existing prefetch chain (profile DB -> local history vector DB)",
  },
  self_reflection: {
    label: "Self-Reflection",
    notes: "Existing second-pass critique and polish",
  },
};

const suggestedPrompts = [
  { icon: "🚶", text: "I'm walking near my pinned GPS — what should I notice here, and what's one affordable next stop?" },
  { icon: "🎨", text: "Best neighborhoods for community street art" },
  { icon: "📸", text: "One free, culturally significant photo spot that's not a tourist trap" },
  { icon: "💰", text: "1-day plan under $30 with history, food, and a sunset (use my profile budget)" },
];

import SpatialTrigger from './components/SpatialTrigger';
import { useGeolocation } from './hooks/useGeolocation';
import { narrator } from './services/NarratorService';

/** Must match backend `config.HERO_CITIES` (itinerary + holiday briefing). */
const CITIES = [
  "Boston",
  "Chicago",
  "Kolkata",
  "Los Angeles",
  "Miami",
  "New York",
  "Philadelphia",
  "San Francisco",
  "Seattle",
  "Washington DC",
];

/** Calendar label for itinerary day 1..N from trip start (YYYY-MM-DD). */
function formatTripDayHeading(isoDateStr, dayNum) {
  if (!isoDateStr || !dayNum) return null;
  const parts = isoDateStr.split("-");
  if (parts.length !== 3) return null;
  const y = parseInt(parts[0], 10);
  const mo = parseInt(parts[1], 10) - 1;
  const d = parseInt(parts[2], 10);
  const dt = new Date(y, mo, d + (dayNum - 1));
  if (Number.isNaN(dt.getTime())) return null;
  const weekday = dt.toLocaleDateString(undefined, { weekday: "long" });
  const rest = dt.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
  return `${weekday} — ${rest}`;
}

export default function WalkieTalkie() {
  const [showMap, setShowMap] = useState(false);
  const [tripMode, setTripMode] = useState("planning");
  const [selectedCity, setSelectedCity] = useState("San Francisco");
  const [llmTier, setLlmTier] = useState("large");
  const [promptStrategy, setPromptStrategy] = useState("self_reflection");
  const [travelDates, setTravelDates] = useState("");
  const [numDays, setNumDays] = useState(1);
  const [numDaysInput, setNumDaysInput] = useState("1");
  const [budget, setBudget] = useState("Moderate");
  const [activeTab, setActiveTab] = useState("itinerary");
  const [itineraryMap, setItineraryMap] = useState(null);
  
  // Live GPS from browser geolocation hook (no simulation mode).
  const { location } = useGeolocation();
  const currentGPS = location || null;

  const [chatByCity, setChatByCity] = useState({});
  const [sessionToken, setSessionToken] = useState(null);
  const [sessionUserId, setSessionUserId] = useState("");
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [hasPromptedGuestSignIn, setHasPromptedGuestSignIn] = useState(false);
  const [authUserId, setAuthUserId] = useState("");
  const [userBudget, setUserBudget] = useState("");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [image, setImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [actionPlan, setActionPlan] = useState([]);
  /** Weather + packing from /api/holiday-briefing when entering Holiday Mode */
  const [holidayBriefing, setHolidayBriefing] = useState(null);
  const fileRef = useRef(null);
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);
  const AUTH_STORAGE_KEY = "walkie_talkie_auth_v1";
  const chatStorageKey = `walkie_talkie_chat_by_city_v1_${sessionUserId || "guest"}`;

  const messages = chatByCity[selectedCity] || [];
  const selectedStrategy = PROMPT_STRATEGIES[promptStrategy] || PROMPT_STRATEGIES.regular;

  const updateCurrentCityMessages = (updater) => {
    setChatByCity((prev) => {
      const current = prev[selectedCity] || [];
      const nextMessages = typeof updater === "function" ? updater(current) : updater;
      return { ...prev, [selectedCity]: nextMessages };
    });
  };

  const getPreviewText = (msg) => {
    if (!msg) return "";
    if (msg.role === "assistant") return (msg.content || "").replace(/\s+/g, " ").trim();
    return (msg.text || "").replace(/\s+/g, " ").trim();
  };

  const chatHistoryItems = CITIES.filter((city) => city === selectedCity || (chatByCity[city] && chatByCity[city].length > 0))
    .map((city) => {
      const thread = chatByCity[city] || [];
      const lastVisible = [...thread].reverse().find((m) => !m.hidden);
      return {
        city,
        count: thread.filter((m) => !m.hidden).length,
        preview: getPreviewText(lastVisible).slice(0, 80),
      };
    });

  useEffect(() => {
    try {
      const authRaw = localStorage.getItem(AUTH_STORAGE_KEY);
      if (authRaw) {
        const auth = JSON.parse(authRaw);
        if (auth?.session_token && auth?.expires_at * 1000 > Date.now()) {
          setSessionToken(auth.session_token);
          setSessionUserId(auth.user_id || "");
          setAuthUserId(auth.user_id || "");
          if (auth.profile?.budget != null) setUserBudget(String(auth.profile.budget));
        }
      }
    } catch {
      // Ignore corrupted local storage payloads.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(chatStorageKey, JSON.stringify(chatByCity));
    } catch {
      // Ignore quota/serialization errors.
    }
  }, [chatByCity, chatStorageKey]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(chatStorageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") setChatByCity(parsed);
        else setChatByCity({});
      } else {
        setChatByCity({});
      }
    } catch {
      setChatByCity({});
    }
  }, [chatStorageKey]);

  const signIn = async () => {
    const uid = (authUserId || "").trim();
    if (!uid) return;
    const budgetNum = parseInt(userBudget, 10);
    const res = await fetch("/api/auth/signin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: uid,
        budget: Number.isFinite(budgetNum) ? budgetNum : undefined,
      }),
    });
    const j = await res.json();
    if (j?.ok && j.session_token) {
      setSessionToken(j.session_token);
      setSessionUserId(j.user_id || uid);
      if (j.profile?.budget != null) setUserBudget(String(j.profile.budget));
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(j));
      setIsAuthModalOpen(false);
      return true;
    }
    return false;
  };

  const saveBudgetPreference = async () => {
    if (!sessionToken) return;
    const n = parseInt(userBudget, 10);
    if (!Number.isFinite(n)) return;
    await fetch("/api/user/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_token: sessionToken, budget: n }),
    });
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "auto" });
  }, [messages.length, loading]);

  /** Neighborhood line for Start Walk — from day 1 of the generated plan, else falls back to city in SpatialTrigger. */
  const walkAreaLabel =
    Array.isArray(itineraryMap) && itineraryMap.length > 0 && itineraryMap[0].locality
      ? itineraryMap[0].locality
      : null;

  useEffect(() => {
    let cancelled = false;
    import("./db/db.js").then((m) => {
      return Promise.all([
        m.getUnvisitedNodes().then((nodes) => {
          if (!cancelled) setActionPlan(nodes);
        }),
        m.getSystemMapping().then((map) => {
          if (!cancelled) setItineraryMap(map);
        }),
      ]);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seed once on load from IndexedDB
  }, []);

  const handleGenerateItinerary = async () => {
    setLoading(true);
    updateCurrentCityMessages(prev => [
      ...prev,
      {
        role: "assistant",
        content: `Waiting for the ${llmTier} itinerary model for ${selectedCity}...`,
      },
    ]);
    const { fetchDynamicNodes, getUnvisitedNodes, getSystemMapping } = await import('./db/db.js');
    try {
        const result = await fetchDynamicNodes(selectedCity, travelDates, numDays, budget, llmTier);
        const unvisited = await getUnvisitedNodes();
        const mapping = await getSystemMapping();
        setActionPlan(unvisited);
        setItineraryMap(mapping);
        if (result?.ok && Array.isArray(mapping) && mapping.length > 0) {
          updateCurrentCityMessages(prev => [
            ...prev,
            {
              role: "assistant",
              content:
                `I've generated a ${numDays}-day itinerary for ${selectedCity}. ` +
                `Switch to Holiday Mode -> Day-to-Day to see each day.`,
            },
          ]);
        } else {
          updateCurrentCityMessages(prev => [
            ...prev,
            {
              role: "assistant",
              content: `I couldn't generate the itinerary right now. Please try again in a bit.`,
            },
          ]);
        }
    } catch (err) {
        updateCurrentCityMessages(prev => [
          ...prev,
          {
            role: "assistant",
            content: `Failed to load itinerary.\nError: ${String(err)}`,
          },
        ]);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (tripMode === 'active') {
      import('./db/db.js').then(module => {
        module.getUnvisitedNodes().then(nodes => setActionPlan(nodes));
        module.getSystemMapping().then(mapping => setItineraryMap(mapping));
      });
    }
  }, [tripMode]);

  useEffect(() => {
    if (tripMode !== "active") {
      setHolidayBriefing(null);
      return;
    }
    let cancelled = false;
    setHolidayBriefing({ loading: true });
    fetch("/api/holiday-briefing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        city: selectedCity,
        start_date: travelDates || null,
        days: numDays,
      }),
    })
      .then((r) => r.json())
      .then((j) => {
        if (!cancelled) setHolidayBriefing({ loading: false, ...j });
      })
      .catch((e) => {
        if (!cancelled) setHolidayBriefing({ loading: false, error: String(e), packing_advice: "" });
      });
    return () => {
      cancelled = true;
    };
  }, [tripMode, selectedCity, travelDates, numDays]);

  const handleMarkCovered = async (nodeId, nodeTitle) => {
    const { markNodeVisited, getUnvisitedNodes } = await import('./db/db.js');
    await markNodeVisited(nodeId);
    const unvisited = await getUnvisitedNodes();
    setActionPlan(unvisited);
    if (sessionToken) {
      fetch("/api/user/visited", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_token: sessionToken,
          city: selectedCity,
          place_name: nodeTitle,
        }),
      }).catch(() => {});
    }
    
    // Proactive trigger to the Assistant (silent reroute logic)
    const systemPromptMsg = `[SYSTEM NUDGE] The user just marked "${nodeTitle}" as completed. Tell them "Great job!" and proactively suggest what they should do next on their itinerary right now.`;
    sendMessage(systemPromptMsg, true);
  };

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      // Ollama expects a raw base64 string without the data URI prefix (e.g. data:image/jpeg;base64,)
      const base64Data = ev.target.result.split(',')[1];
      setImage({ data: base64Data, type: file.type });
      setImagePreview(ev.target.result);
    };
    reader.readAsDataURL(file);
  };

  const sendMessage = async (text, isHidden = false) => {
    if (!sessionToken && !hasPromptedGuestSignIn) {
      updateCurrentCityMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Please sign in to keep your conversation history, visited places, and budget preferences synced." },
      ]);
      setIsAuthModalOpen(true);
      setHasPromptedGuestSignIn(true);
      // Continue as guest so first-time users still get a model response.
    }
    const userText = (typeof text === 'string' ? text : null) || input.trim();
    if (!userText && !image) return;

    // Handle resume logic if user says yes to continuing the story
    if (narrator.synth && narrator.synth.paused && userText.match(/^(yes|yeah|sure|yep|please|go ahead|finish)/i)) {
        narrator.resume();
        const newMessages = [...messages, { role: "user", text: userText }, { role: "assistant", content: "Resuming the story..." }];
        updateCurrentCityMessages(newMessages);
        setInput("");
        return;
    }

    let isInterrupting = false;
    let topicToRestore = "";
    if (narrator.isSpeaking()) {
        narrator.pause();
        isInterrupting = true;
        topicToRestore = narrator.currentTopic || "this location";
    }

    const userContent = [];
    if (image) {
      userContent.push({ type: "image", source: { type: "base64", media_type: image.type, data: image.data } });
    }
    if (userText) {
      userContent.push({ type: "text", text: userText });
    }

    const newMessages = [...messages, { role: "user", content: userContent, preview: imagePreview, text: userText, hidden: isHidden }];
    updateCurrentCityMessages(newMessages);
    setInput("");
    setImage(null);
    setImagePreview(null);
    if (!isHidden) setLoading(true);

    const apiMessages = newMessages.map((m) => {
      // Extract text content (Ollama expects content to be a string)
      let textContent = "";
      if (typeof m.content === "string") {
        textContent = m.content;
      } else if (Array.isArray(m.content)) {
        const textBlock = m.content.find((b) => b.type === "text");
        textContent = textBlock ? textBlock.text : "";
      }

      // If user uploaded an image, prepare it for Ollama Vision models (like llama3.2-vision)
      let images = undefined;
      // In our state, m.content is an array of objects for user messages
      if (m.role === "user" && Array.isArray(m.content)) {
        const imageBlocks = m.content.filter((b) => b.type === "image");
        if (imageBlocks.length > 0) {
          images = imageBlocks.map(b => b.source.data);
        }
      }

      return {
        role: m.role,
        content: textContent,
        ...(images && { images }),
      };
    });

    if (isInterrupting) {
        const lastMsg = apiMessages[apiMessages.length - 1];
        lastMsg.content = `[SYSTEM NOTE: The user just interrupted an ongoing audio narration about ${topicToRestore} to say this. Answer their question concisely, and end your response by asking if they would like you to finish the story.]\n\nUser: ` + lastMsg.content;
    }

    try {
      const hasImage = apiMessages.some(m => m.images);
      const lat = currentGPS?.lat ?? null;
      const lng = currentGPS?.lng ?? null;
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: hasImage ? "vision" : llmTier,
          llm_tier: llmTier,
          messages: [
            { role: "system", content: (hasImage ? VISION_SYSTEM_PROMPT : SYSTEM_PROMPT) + `\n\n[CONTEXT: User focus city is ${selectedCity}; travel dates: ${travelDates || "TBD"}.]` },
            ...apiMessages
          ],
          stream: true,
          latitude: lat,
          longitude: lng,
          city: selectedCity,
          session_token: sessionToken,
          prompting_mode: promptStrategy,
        }),
      });

      if (!res.ok) throw new Error("Network response was not ok");
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      setLoading(false); // Turn off loading dots as soon as stream starts

      let fullReply = "";
      let appendedAssistant = false;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.trim() !== '') {
            try {
              const parsed = JSON.parse(line);
              if (parsed.message?.content) {
                fullReply += parsed.message.content;
                updateCurrentCityMessages((prev) => {
                  if (!appendedAssistant) {
                    appendedAssistant = true;
                    return [...prev, { role: "assistant", content: fullReply }];
                  }
                  const newMsgs = [...prev];
                  const lastIdx = newMsgs.length - 1;
                  if (lastIdx >= 0 && newMsgs[lastIdx].role === "assistant") {
                    newMsgs[lastIdx] = { ...newMsgs[lastIdx], content: fullReply };
                  } else {
                    newMsgs.push({ role: "assistant", content: fullReply });
                  }
                  return newMsgs;
                });
              }
            } catch (e) {
              // Ignore JSON parse errors for incomplete chunks
            }
          }
        }
      }
    } catch (err) {
      updateCurrentCityMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Could not reach the API backend. Check uvicorn on :8000 and OpenRouter settings in backend/.env." },
      ]);
      setLoading(false);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const formatText = (text) => {
    const renderPipeTables = (raw) => {
      const lines = raw.split("\n");
      const out = [];
      let i = 0;

      const isPipeRow = (line) => {
        const t = line.trim();
        return (t.match(/\|/g) || []).length >= 2;
      };
      const isSeparatorRow = (line) => {
        const t = line.trim();
        return isPipeRow(t) && /^[\|\s:\-]+$/.test(t);
      };
      const splitCells = (line) => {
        const t = line.trim();
        const normalized = t.startsWith("|") ? t.slice(1) : t;
        const normalized2 = normalized.endsWith("|") ? normalized.slice(0, -1) : normalized;
        return normalized2.split("|").map((c) => c.trim());
      };

      while (i < lines.length) {
        let j = i + 1;
        while (j < lines.length && lines[j].trim() === "") j += 1;
        if (j < lines.length && isPipeRow(lines[i]) && isSeparatorRow(lines[j])) {
          const headerCells = splitCells(lines[i]);
          i = j + 1;
          const bodyRows = [];
          while (i < lines.length && isPipeRow(lines[i])) {
            bodyRows.push(splitCells(lines[i]));
            i += 1;
          }

          const headHtml = `<tr>${headerCells.map((c) => `<th>${c}</th>`).join("")}</tr>`;
          const bodyHtml = bodyRows
            .map((row) => `<tr>${row.map((c) => `<td>${c}</td>`).join("")}</tr>`)
            .join("");

          out.push(
            `<div class="md-table-wrap"><table class="md-table"><thead>${headHtml}</thead><tbody>${bodyHtml}</tbody></table></div>`
          );
          continue;
        }
        out.push(lines[i]);
        i += 1;
      }
      return out.join("\n");
    };

    const withTables = renderPipeTables(text);
    return withTables
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/🗝️[^\n]*/g, (m) => `<span class="local-secret">${m}</span>`)
      .replace(/Local Secret[^\n]*/g, (m) => `<span class="local-secret">🗝️ ${m}</span>`)
      .replace(/\n/g, "<br>")
      .replace(/<br>\s*<div class="md-table-wrap">/g, '<div class="md-table-wrap">')
      .replace(/<\/div>\s*<br>/g, "</div>");
  };

  const isEmpty = messages.length === 0;

  return (
    <div style={{ fontFamily: "'Georgia', serif", minHeight: "100vh", background: "#0f0e0b", color: "#f0ead6", display: "flex", flexDirection: "column" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;1,400&family=Source+Serif+4:wght@300;400;600&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0f0e0b; }
        .app { font-family: 'Source Serif 4', serif; }
        .header { 
          padding: 20px 24px 16px; 
          border-bottom: 1px solid #2a2820;
          display: flex; align-items: center; gap: 12px;
          background: #0f0e0b;
          position: sticky; top: 0; z-index: 10;
        }
        .logo-mark {
          width: 40px; height: 40px;
          background: linear-gradient(135deg, #c8a96e, #8b6914);
          border-radius: 10px;
          display: flex; align-items: center; justify-content: center;
          font-size: 20px;
        }
        .brand { font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 700; color: #c8a96e; letter-spacing: -0.5px; }
        .tagline { font-size: 11px; color: #6b6452; text-transform: uppercase; letter-spacing: 2px; margin-top: 1px; }
        
        .main-layout { display: flex; flex: 1; min-height: 0; }
        .history-pane {
          width: 250px; border-right: 1px solid #2a2820; background: #12110d;
          padding: 14px 10px; overflow-y: auto;
        }
        .history-title {
          color: #8a7d66; font-size: 11px; text-transform: uppercase; letter-spacing: 1.3px;
          margin: 4px 8px 10px; font-weight: 700;
        }
        .history-item {
          width: 100%; text-align: left; background: transparent; border: 1px solid transparent;
          border-radius: 10px; color: #c4b69a; padding: 10px; cursor: pointer; margin-bottom: 8px;
        }
        .history-item:hover { border-color: #c8a96e33; background: #1a1810; }
        .history-item.active { border-color: #c8a96e66; background: #1a1810; }
        .history-city { font-size: 13px; color: #f0ead6; font-weight: 600; margin-bottom: 3px; }
        .history-meta { font-size: 11px; color: #8a7d66; margin-bottom: 2px; }
        .history-preview { font-size: 11px; color: #9f9278; line-height: 1.35; }

        .chat-area-wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; }
        .chat-area { flex: 1; overflow-y: auto; padding: 24px 16px; max-width: 780px; margin: 0 auto; width: 100%; }
        
        .welcome { text-align: center; padding: 48px 20px 32px; }
        .welcome h1 { font-family: 'Playfair Display', serif; font-size: 36px; color: #c8a96e; margin-bottom: 8px; }
        .welcome p { color: #8a7d66; font-size: 15px; line-height: 1.6; max-width: 480px; margin: 0 auto 32px; }
        
        .suggestions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 600px; margin: 0 auto; }
        .suggestion-btn {
          background: #1a1810; border: 1px solid #2a2820;
          color: #c4b69a; padding: 12px 14px; border-radius: 10px;
          cursor: pointer; text-align: left; font-family: 'Source Serif 4', serif;
          font-size: 13px; line-height: 1.4; transition: all 0.2s;
          display: flex; gap: 8px; align-items: flex-start;
        }
        .suggestion-btn:hover { background: #22201a; border-color: #c8a96e44; color: #f0ead6; }
        .suggestion-icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
        
        .message { margin-bottom: 24px; display: flex; gap: 12px; animation: fadeUp 0.3s ease; }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .message.user { flex-direction: row-reverse; }
        .avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; margin-top: 2px; }
        .avatar.ai { background: linear-gradient(135deg, #c8a96e, #8b6914); }
        .avatar.user { background: #2a2820; }
        .bubble { max-width: 78%; padding: 14px 16px; border-radius: 14px; font-size: 14.5px; line-height: 1.7; }
        .bubble.ai { background: #1a1810; border: 1px solid #2a2820; color: #ddd5c0; border-radius: 4px 14px 14px 14px; }
        .bubble.user { background: linear-gradient(135deg, #c8a96e22, #8b691422); border: 1px solid #c8a96e33; color: #f0ead6; border-radius: 14px 4px 14px 14px; }
        .local-secret { display: block; margin-top: 12px; padding: 10px 12px; background: #c8a96e11; border-left: 2px solid #c8a96e; border-radius: 0 8px 8px 0; color: #c8a96e; font-style: italic; font-size: 13.5px; }
        .md-table-wrap {
          margin: 14px 0;
          overflow-x: auto;
          border: 1px solid #c8a96e33;
          border-radius: 10px;
          background: #16140f;
        }
        .md-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13.5px;
          line-height: 1.45;
        }
        .md-table th, .md-table td {
          padding: 8px 10px;
          border-bottom: 1px solid #2f2a20;
          border-right: 1px solid #2f2a20;
          vertical-align: top;
          text-align: left;
          white-space: normal;
        }
        .md-table th:last-child, .md-table td:last-child { border-right: none; }
        .md-table tbody tr:last-child td { border-bottom: none; }
        .md-table th {
          color: #d8c59a;
          font-weight: 700;
          background: #201c14;
        }
        .md-table td { color: #ddd5c0; }
        .img-preview { max-width: 200px; border-radius: 8px; margin-bottom: 8px; display: block; }
        
        .typing { display: flex; gap: 4px; align-items: center; padding: 14px 16px; }
        .dot { width: 6px; height: 6px; background: #c8a96e; border-radius: 50%; animation: bounce 1.2s infinite; }
        .dot:nth-child(2) { animation-delay: 0.2s; }
        .dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; } 40% { transform: scale(1); opacity: 1; } }
        
        .input-area { 
          padding: 16px; border-top: 1px solid #2a2820;
          background: #0f0e0b;
          position: sticky; bottom: 0;
          z-index: 5;
        }
        .input-wrap { max-width: 780px; margin: 0 auto; display: flex; gap: 8px; align-items: flex-end; }
        .img-attach-preview { position: relative; margin-bottom: 8px; }
        .img-attach-preview img { width: 64px; height: 64px; object-fit: cover; border-radius: 8px; border: 1px solid #c8a96e44; }
        .remove-img { position: absolute; top: -6px; right: -6px; width: 18px; height: 18px; background: #c8a96e; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 10px; color: #0f0e0b; font-weight: bold; border: none; }
        .inner-wrap { flex: 1; background: #1a1810; border: 1px solid #2a2820; border-radius: 14px; overflow: hidden; transition: border-color 0.2s; }
        .inner-wrap:focus-within { border-color: #c8a96e55; }
        .attach-row { display: flex; gap: 4px; padding: 8px 10px 0; }
        .attach-btn { background: none; border: none; color: #6b6452; cursor: pointer; padding: 4px; border-radius: 6px; font-size: 16px; transition: color 0.2s; }
        .attach-btn:hover { color: #c8a96e; }
        textarea { 
          width: 100%; background: none; border: none; outline: none; 
          color: #f0ead6; font-family: 'Source Serif 4', serif; font-size: 14.5px; 
          padding: 8px 12px 10px; resize: none; min-height: 44px; max-height: 140px; line-height: 1.5;
        }
        textarea::placeholder { color: #4a4438; }
        .send-btn { 
          width: 42px; height: 42px; border-radius: 12px; 
          background: linear-gradient(135deg, #c8a96e, #8b6914);
          border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
          color: #0f0e0b; font-size: 18px; transition: opacity 0.2s; flex-shrink: 0;
        }
        .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .send-btn:hover:not(:disabled) { opacity: 0.85; }
        .hint { text-align: center; font-size: 11px; color: #3a3428; margin-top: 8px; }
      `}</style>

      <div className="app" style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
        {isAuthModalOpen && (
          <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)", zIndex: 999, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ background: "#1a1810", border: "1px solid #c8a96e55", borderRadius: "12px", padding: "18px", width: "min(420px, 92vw)" }}>
              <h3 style={{ color: "#c8a96e", marginBottom: "8px", fontFamily: "'Playfair Display', serif" }}>Sign in to continue</h3>
              <p style={{ color: "#c4b69a", fontSize: "13px", marginBottom: "12px" }}>We keep your city-wise chat history, visited places, and budget for 24 hours.</p>
              <input
                placeholder="User ID (e.g., spartan)"
                value={authUserId}
                onChange={(e) => setAuthUserId(e.target.value)}
                style={{ width: "100%", marginBottom: "10px", background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "8px 10px", borderRadius: "8px" }}
              />
              <input
                type="number"
                placeholder="Budget/day (optional)"
                value={userBudget}
                onChange={(e) => setUserBudget(e.target.value)}
                style={{ width: "100%", marginBottom: "12px", background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "8px 10px", borderRadius: "8px" }}
              />
              <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                <button onClick={() => setIsAuthModalOpen(false)} style={{ background: "transparent", color: "#c4b69a", border: "1px solid #3a3428", padding: "7px 12px", borderRadius: "8px" }}>Later</button>
                <button onClick={signIn} style={{ background: "#8b6914", color: "#0f0e0b", border: "none", padding: "7px 12px", borderRadius: "8px", fontWeight: "bold" }}>Sign in</button>
              </div>
            </div>
          </div>
        )}
        {showMap && (
          <SpatialTrigger
            city={selectedCity}
            areaLabel={walkAreaLabel}
            llmTier={llmTier}
            onClose={() => setShowMap(false)}
          />
        )}
        <div className="header">
          <div className="logo-mark">🗺️</div>
          <div style={{ flex: 1 }}>
            <div className="brand">WalkieTalkie</div>
            <div className="tagline">Local Intel · Budget Travel · Hidden Cities</div>
          </div>
          
          <div style={{ display: 'flex', background: '#2a2820', borderRadius: '20px', padding: '4px', marginRight: '8px' }}>
            <button
                type="button"
                onClick={() => setTripMode("planning")}
                style={{ background: tripMode === "planning" ? '#c8a96e' : 'transparent', color: tripMode === "planning" ? '#0f0e0b' : '#8a7d66', border: 'none', padding: '6px 14px', borderRadius: '16px', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer', transition: 'all 0.2s' }}>
                Plan Itinerary
            </button>
            <button
                type="button"
                onClick={() => setTripMode("active")}
                style={{ background: tripMode === "active" ? '#c8a96e' : 'transparent', color: tripMode === "active" ? '#0f0e0b' : '#8a7d66', border: 'none', padding: '6px 14px', borderRadius: '16px', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer', transition: 'all 0.2s' }}>
                Holiday Mode
            </button>
            {tripMode === "active" && (
              <button
                  type="button"
                  title="Sends a coach-style check-in to the guide (energy, snack break vs pace). Not a clock — switch to Plan Itinerary to read the assistant reply in chat."
                  onClick={() => {
                    const systemPromptMsg = `[SYSTEM AUTOMATION] Time jump simulation: The afternoon is passing quickly and the user still has ${actionPlan.length} places left. Proactively ask how they are doing and suggest either taking a break for a snack or picking up the pace!`;
                    sendMessage(systemPromptMsg, true);
                  }}
                  style={{ background: 'transparent', color: '#8b6914', border: '1px solid #8b691444', padding: '6px 14px', borderRadius: '16px', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer', transition: 'all 0.2s', marginLeft: '8px' }}>
                  Day check-in ⏱️
              </button>
            )}
          </div>

          <button
            style={{ background: '#c8a96e', color: '#0f0e0b', border: 'none', padding: '8px 16px', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px' }}
            onClick={() => setShowMap(true)}
          >
            Start Walk
          </button>
        </div>

        {tripMode === "planning" && (
        <div style={{ padding: "12px 24px", background: "#1a1810", borderBottom: "1px solid #2a2820", display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
           <span style={{ fontSize: "12px", color: "#8a7d66", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "bold" }}>City:</span>
           <select 
              value={selectedCity}
              onChange={e => setSelectedCity(e.target.value)}
              style={{ background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "6px 12px", borderRadius: "8px", outline: "none", fontSize: "14px", fontFamily: "inherit", cursor: "pointer" }}
           >
              {CITIES.map(c => <option key={c} value={c}>{c}</option>)}
           </select>

           <span style={{ fontSize: "12px", color: "#8a7d66", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "bold", marginLeft: "8px" }}>Model tier:</span>
           <select
              value={llmTier}
              onChange={(e) => setLlmTier(e.target.value)}
              title="Small vs large OpenRouter model (rubric comparison)"
              style={{ background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "6px 12px", borderRadius: "8px", outline: "none", fontSize: "14px", fontFamily: "inherit", cursor: "pointer" }}
           >
              <option value="large">Large (nvidia/nemotron-3-nano-30b-a3b:free)</option>
              <option value="small">Small (nvidia/nemotron-nano-9b-v2:free)</option>
           </select>

           <span style={{ fontSize: "12px", color: "#8a7d66", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "bold", marginLeft: "8px" }}>Prompt strategy:</span>
           <select
              value={promptStrategy}
              onChange={(e) => setPromptStrategy(e.target.value)}
              title="Switch prompting method to compare response quality"
              style={{ background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "6px 12px", borderRadius: "8px", outline: "none", fontSize: "14px", fontFamily: "inherit", cursor: "pointer", minWidth: "190px" }}
           >
              {Object.entries(PROMPT_STRATEGIES).map(([value, cfg]) => (
                <option key={value} value={value}>
                  {cfg.label}
                </option>
              ))}
           </select>
           
           <span style={{ fontSize: "12px", color: "#8a7d66", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "bold", marginLeft: "8px" }}>Days:</span>
           <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={numDaysInput}
              onChange={(e) => {
                const v = e.target.value.replace(/[^\d]/g, "");
                if (v.length <= 2) setNumDaysInput(v);
              }}
              onBlur={() => {
                const n = parseInt(numDaysInput, 10);
                const safe = Number.isFinite(n) ? Math.min(14, Math.max(1, n)) : 1;
                setNumDays(safe);
                setNumDaysInput(String(safe));
              }}
              title="Number of days for this trip (used when you generate the itinerary)"
              style={{ width: "56px", background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "6px 8px", borderRadius: "8px", outline: "none", fontSize: "14px", fontFamily: "inherit" }}
           />
           <span style={{ fontSize: "12px", color: "#8a7d66", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "bold", marginLeft: "8px" }}>My budget/day:</span>
           <input
              type="number"
              min={0}
              value={userBudget}
              onChange={(e) => setUserBudget(e.target.value)}
              onBlur={saveBudgetPreference}
              placeholder="USD"
              title="Saved to your profile when signed in"
              style={{ width: "84px", background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "6px 8px", borderRadius: "8px", outline: "none", fontSize: "14px", fontFamily: "inherit" }}
           />

           <span style={{ fontSize: "12px", color: "#8a7d66", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "bold", marginLeft: "8px" }}>Start date:</span>
           <input 
              type="date"
              value={travelDates}
              onChange={e => setTravelDates(e.target.value)}
              style={{ background: "#2a2820", color: "#f0ead6", border: "1px solid #c8a96e44", padding: "5px 12px", borderRadius: "8px", outline: "none", fontSize: "14px", fontFamily: "inherit", colorScheme: "dark", cursor: "pointer" }}
           />
           
           <button 
              onClick={handleGenerateItinerary}
              disabled={loading}
              style={{ background: '#8b6914', color: '#0f0e0b', border: 'none', padding: '6px 14px', borderRadius: '16px', fontSize: '13px', fontWeight: 'bold', cursor: 'pointer', opacity: loading ? 0.5 : 1 }}>
              Generate itinerary
           </button>
        </div>
        )}

        <div className="main-layout">
        {tripMode === "planning" && (
          <aside className="history-pane">
            <div className="history-title">Chat History by Location</div>
            {chatHistoryItems.map((item) => (
              <button
                key={item.city}
                className={`history-item ${item.city === selectedCity ? "active" : ""}`}
                onClick={() => setSelectedCity(item.city)}
              >
                <div className="history-city">{item.city}</div>
                <div className="history-meta">{item.count} message{item.count === 1 ? "" : "s"}</div>
                <div className="history-preview">{item.preview || "No messages yet."}</div>
              </button>
            ))}
          </aside>
        )}

        <div className="chat-area-wrap">
        <div className="chat-area" style={{ flex: 1 }}>
          {tripMode === 'active' ? (
             <div className="action-plan">
               <h2 style={{ fontFamily: "'Playfair Display', serif", color: "#c8a96e", marginBottom: "6px" }}>Holiday Action Plan</h2>
               <p style={{ color: "#8a7d66", fontSize: "14px", marginBottom: "16px", lineHeight: 1.5 }}>
                 {Array.isArray(itineraryMap) && itineraryMap.length > 0 ? (
                   <>Day-to-day shows <strong style={{ color: "#c8a96e" }}>{itineraryMap.length} day{itineraryMap.length === 1 ? "" : "s"}</strong> from your last generated plan.</>
                 ) : (
                   <>No multi-day plan loaded yet — set <strong style={{ color: "#c8a96e" }}>Days</strong> in Plan Itinerary and tap Generate itinerary.</>
                 )}
                 {!travelDates && (
                   <span> Add a <strong style={{ color: "#c8a96e" }}>Start date</strong> to see weekday + calendar dates on each day.</span>
                 )}
               </p>

               {holidayBriefing?.loading && (
                 <p style={{ color: "#8a7d66", fontSize: "14px", marginBottom: "16px" }}>Looking up weather and packing ideas for your dates…</p>
               )}
               {holidayBriefing && !holidayBriefing.loading && holidayBriefing.packing_advice && (
                 <div
                   style={{
                     background: "#1a1810",
                     border: "1px solid #c8a96e44",
                     borderRadius: "12px",
                     padding: "16px",
                     marginBottom: "20px",
                   }}
                 >
                   <h3 style={{ fontFamily: "'Playfair Display', serif", color: "#c8a96e", fontSize: "17px", marginBottom: "10px" }}>
                     Weather & what to pack
                   </h3>
                   <div style={{ color: "#ddd5c0", fontSize: "14px", lineHeight: 1.65, whiteSpace: "pre-wrap" }}>
                     {holidayBriefing.packing_advice}
                   </div>
                 </div>
               )}
               {holidayBriefing && !holidayBriefing.loading && holidayBriefing.error && !holidayBriefing.packing_advice && (
                 <p style={{ color: "#b08070", fontSize: "14px", marginBottom: "16px" }}>{holidayBriefing.error}</p>
               )}
               
               <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
                 <button onClick={() => setActiveTab('places')} style={{ background: activeTab === 'places' ? '#8b6914' : '#2a2820', color: activeTab === 'places' ? '#0f0e0b' : '#f0ead6', border: 'none', padding: '6px 14px', borderRadius: '16px', fontWeight: 'bold', cursor: 'pointer' }}>All Places</button>
                 <button onClick={() => setActiveTab('eats')} style={{ background: activeTab === 'eats' ? '#8b6914' : '#2a2820', color: activeTab === 'eats' ? '#0f0e0b' : '#f0ead6', border: 'none', padding: '6px 14px', borderRadius: '16px', fontWeight: 'bold', cursor: 'pointer' }}>Must Eats</button>
                 <button onClick={() => setActiveTab('itinerary')} style={{ background: activeTab === 'itinerary' ? '#8b6914' : '#2a2820', color: activeTab === 'itinerary' ? '#0f0e0b' : '#f0ead6', border: 'none', padding: '6px 14px', borderRadius: '16px', fontWeight: 'bold', cursor: 'pointer' }}>Day-to-Day</button>
               </div>

               {actionPlan.length === 0 ? (
                 <p style={{ color: "#8a7d66" }}>Your itinerary is empty or finished! Switch to Plan Itinerary and tap Generate itinerary.</p>
               ) : (
                 <>
                   {(activeTab === 'places' || activeTab === 'eats') && (
                     actionPlan.filter(n => activeTab === 'places' ? n.type === 'place' : n.type === 'eat').map(node => (
                       <div key={node.id} style={{ background: "#1a1810", border: "1px solid #2a2820", padding: "16px", borderRadius: "12px", marginBottom: "12px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                         <div>
                           <h3 style={{ fontSize: "16px", color: "#f0ead6", marginBottom: "4px" }}>{node.title}</h3>
                           <p style={{ fontSize: "13px", color: "#8a7d66", maxWidth: "450px" }}>{node.anecdote}</p>
                         </div>
                         <button 
                           onClick={() => handleMarkCovered(node.id, node.title)}
                           style={{ background: "#2a2820", color: "#c8a96e", border: "1px solid #c8a96e44", padding: "8px 16px", borderRadius: "8px", cursor: "pointer", fontWeight: "bold" }}>
                           ✓ Covered
                         </button>
                       </div>
                     ))
                   )}
                   {activeTab === 'itinerary' && itineraryMap && itineraryMap.map((dayInfo) => {
                     const calendarLine = formatTripDayHeading(travelDates, dayInfo.day);
                     return (
                     <div key={dayInfo.day} style={{ marginBottom: '24px' }}>
                       <h3 style={{ color: '#c8a96e', marginBottom: '6px', borderBottom: '1px solid #c8a96e44', paddingBottom: '8px', fontSize: '17px' }}>
                         Day {dayInfo.day}
                         {calendarLine ? (
                           <span style={{ color: '#c4b69a', fontWeight: 'normal', fontSize: '15px' }}> · {calendarLine}</span>
                         ) : null}
                       </h3>
                       {dayInfo.locality ? (
                         <p style={{ color: '#8a7d66', fontSize: '13px', margin: '0 0 12px', lineHeight: 1.45 }}>
                           <strong style={{ color: '#c4b69a', fontWeight: 600 }}>Area focus:</strong> {dayInfo.locality} — same-day stops are grouped for walking this neighborhood.
                         </p>
                       ) : null}
                       {dayInfo.plan.map(nodeId => {
                         const node = actionPlan.find(n => n.id === nodeId);
                         if (!node) return null; // Already covered!
                         return (
                           <div key={node.id} style={{ background: "#2a2820", padding: "12px", borderRadius: "8px", marginBottom: "8px", display: "flex", justifyContent: "space-between" }}>
                             <span style={{ color: '#f0ead6', fontWeight: 'bold' }}>{node.title} <span style={{ color: '#8a7d66', fontSize: '11px', marginLeft: '8px', textTransform: 'uppercase' }}>{node.type}</span></span>
                             <button onClick={() => handleMarkCovered(node.id, node.title)} style={{ background: "transparent", color: "#c8a96e", border: "1px solid #c8a96e44", padding: "4px 8px", borderRadius: "6px", cursor: "pointer", fontSize: "12px" }}>✓ Covered</button>
                           </div>
                         );
                       })}
                     </div>
                   );
                   })}
                 </>
               )}
             </div>
          ) : isEmpty ? (
            <div className="welcome">
              <h1>Explore Like a Local</h1>
              <p>I know the spots that don't show up on travel blogs — the century-old tea stall, the mural with a story, the $4 meal that locals swear by.</p>
              <div className="suggestions">
                {suggestedPrompts.map((p, i) => (
                  <button key={i} className="suggestion-btn" onClick={() => sendMessage(p.text)}>
                    <span className="suggestion-icon">{p.icon}</span>
                    <span>{p.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, i) => (
              msg.hidden ? null : (
                <div key={i} className={`message ${msg.role}`}>
                  <div className={`avatar ${msg.role === "assistant" ? "ai" : "user"}`}>
                    {msg.role === "assistant" ? "🗺️" : "✈️"}
                  </div>
                  <div className={`bubble ${msg.role === "assistant" ? "ai" : "user"}`}>
                    {msg.preview && <img src={msg.preview} alt="uploaded" className="img-preview" />}
                    {msg.role === "assistant"
                      ? <div dangerouslySetInnerHTML={{ __html: formatText(msg.content) }} />
                      : <span>{msg.text}</span>
                    }
                  </div>
                </div>
              )
            ))
          )}
          {loading && tripMode === "planning" && (
            <div className="message">
              <div className="avatar ai">🗺️</div>
              <div className="bubble ai">
                <div className="typing">
                  <div className="dot" /><div className="dot" /><div className="dot" />
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {tripMode === "planning" && (
          <div className="input-area">
            <div className="input-wrap">
            <div style={{ flex: 1 }}>
              {imagePreview && (
                <div className="img-attach-preview">
                  <img src={imagePreview} alt="preview" />
                  <button className="remove-img" onClick={() => { setImage(null); setImagePreview(null); }}>✕</button>
                </div>
              )}
              <div className="inner-wrap">
                <div className="attach-row">
                  <button className="attach-btn" title="Upload image" onClick={() => fileRef.current?.click()}>📷</button>
                  <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleImageUpload} />
                </div>
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKey}
                  placeholder="Ask about a city, neighborhood, food spot, or upload a photo..."
                  rows={1}
                  onInput={(e) => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; }}
                />
              </div>
            </div>
            <button className="send-btn" onClick={() => sendMessage()} disabled={loading || (!input.trim() && !image)}>
              ↑
            </button>
          </div>
          <div className="hint">
            Prompt strategy: {selectedStrategy.label} · Upload photos of menus, murals, or buildings for instant local insight
          </div>
        </div>
        )}
        </div>
        </div>
      </div>
    </div>
  );
}