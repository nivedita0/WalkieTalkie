import { openDB } from 'idb';

const DB_NAME = 'WalkieTalkieVault';
const STORE_NAME = 'nodes';

export async function initDB() {
    const db = await openDB(DB_NAME, 1, {
        upgrade(db) {
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME, { keyPath: 'id' });
            }
        },
    });

    // If we want to seed defaults, we could do it here, but we will rely on fetchDynamicNodes.
    
    return db;
}

export async function fetchDynamicNodes(city, dates, days, budget, llmTier = 'large') {
    const db = await initDB();
    try {
        const response = await fetch('/api/synthesize-itinerary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ city, dates, days, budget, llm_tier: llmTier })
        });
        const dynamicPayload = await response.json();
        const backendError = dynamicPayload?.error ? String(dynamicPayload.error) : "";
        const debug = dynamicPayload?._debug || null;
        const placesLen = Array.isArray(dynamicPayload?.places) ? dynamicPayload.places.length : 0;
        const itineraryLen = Array.isArray(dynamicPayload?.itinerary) ? dynamicPayload.itinerary.length : 0;
        
        if (
            dynamicPayload &&
            Array.isArray(dynamicPayload.places) &&
            Array.isArray(dynamicPayload.itinerary) &&
            dynamicPayload.itinerary.length > 0
        ) {
            const tx = db.transaction(STORE_NAME, 'readwrite');
            
            // Clear existing nodes before overwriting to prevent ID conflicts from changing cities
            await tx.store.clear();
            
            const places = dynamicPayload.places || [];
            const eats = dynamicPayload.eats || [];
            const allNodes = [...places, ...eats];
            const placeIds = new Set(places.map((p) => p && p.id).filter(Boolean));

            for (const node of allNodes) {
                if (!node || !node.id) continue;
                node.visited = false;
                node.lastVisited = null;
                node.type = placeIds.has(node.id) ? 'place' : 'eat';
                tx.store.put(node);
            }
            
            tx.store.put({
               id: 'SYSTEM_ITINERARY_MAPPING',
               data: dynamicPayload.itinerary
            });

            await tx.done;
            return {
                ok: true,
                error: null,
                debug,
                counts: { places: placesLen, itineraryDays: itineraryLen },
            };
        }
        return {
            ok: false,
            error: backendError || "Backend returned no itinerary days.",
            debug,
            counts: { places: placesLen, itineraryDays: itineraryLen },
            raw: JSON.stringify(dynamicPayload).slice(0, 1200),
        };
    } catch (e) {
        console.error("Failed to fetch dynamic itinerary nodes:", e);
        return {
            ok: false,
            error: String(e),
            debug: null,
            counts: { places: 0, itineraryDays: 0 },
            raw: "",
        };
    }
}

export async function getUnvisitedNodes() {
    const db = await initDB();
    const nodes = await db.getAll(STORE_NAME);
    return nodes.filter(n => !n.visited && n.id !== 'SYSTEM_ITINERARY_MAPPING');
}

export async function getSystemMapping() {
    const db = await initDB();
    const map = await db.get(STORE_NAME, 'SYSTEM_ITINERARY_MAPPING');
    return map ? map.data : null;
}

export async function getNodes() {
    const db = await initDB();
    let nodes = await db.getAll(STORE_NAME);
    nodes = nodes.filter(n => n.id !== 'SYSTEM_ITINERARY_MAPPING');
    const now = Date.now();
    const COOLDOWN_MS = 30 * 60 * 1000; // 30 minutes
    return nodes.map(n => ({
        ...n,
        locked: n.lastVisited ? (now - n.lastVisited < COOLDOWN_MS) : false
    }));
}

export async function markNodeVisited(id) {
    const db = await initDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const node = await tx.store.get(id);
    if (node) {
        node.visited = true;          // Overall discovery tracking
        node.lastVisited = Date.now(); // Proximity Cooldown
        await tx.store.put(node);
    }
    await tx.done;
}

export async function resetVisited() {
    const db = await initDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const nodes = await tx.store.getAll();
    for (const node of nodes) {
        node.visited = false;
        node.lastVisited = null;
        tx.store.put(node);
    }
    await tx.done;
}
