import backend from "../../api/backend";
import "./CampaignHistory.css";
import { useEffect, useState } from "react";

interface CampaignEvent {
  occurred_at: string;
  category: string;
  title: string;
  details: string;
}

const REFRESH_INTERVAL_MS = 5000;

export default function CampaignHistory() {
  const [events, setEvents] = useState<CampaignEvent[]>([]);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      backend
        .get<CampaignEvent[]>("/game/history", { params: { limit: 100 } })
        .then((response) => {
          if (active) {
            setEvents(response.data);
          }
        })
        .catch((error) =>
          console.error(`Error fetching campaign history: ${error}`)
        );
    };

    refresh();
    const timer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <details className="campaign-history">
      <summary>Campaign history ({events.length})</summary>
      <div className="campaign-history-list">
        {events.length === 0 ? (
          <p className="campaign-history-empty">No strategic events yet.</p>
        ) : (
          events.map((event, index) => (
            <article
              className="campaign-history-event"
              key={`${event.occurred_at}-${event.category}-${index}`}
            >
              <header>
                <time>{new Date(event.occurred_at).toLocaleString()}</time>
                <span>{event.category}</span>
              </header>
              <strong>{event.title}</strong>
              {event.details && <p>{event.details}</p>}
            </article>
          ))
        )}
      </div>
    </details>
  );
}

