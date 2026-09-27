import { useEffect, useState } from "react";
import "./App.css";

type Choice = "H" | "D" | "A";

type Bet = {
  id: number;
  league: string;
  home: string;
  away: string;
  selection: Choice;
  odds: number;
  amount: number;
  status: "abierta" | "ganada" | "perdida";
  returned_amount: number | null;
  estimated_probability: number | null;
  kickoff_utc: string | null;
  match_date: string;
  final_result: Choice | null;
  home_odds: number | null;
  draw_odds: number | null;
  away_odds: number | null;
  source_url: string;
};

type UpcomingMatch = {
  fixture_id: number;
  kickoff_utc: string;
  league: string;
  home: string;
  away: string;
  odds: Record<Choice, number>;
  probabilities: Record<Choice, number>;
  source: string;
};

type Experiment = {
  starting_balance: number;
  available: number;
  invested: number;
  net: number;
  bets: Bet[];
  archived_bets: Bet[];
  upcoming_matches: UpcomingMatch[];
  upcoming_error: string | null;
};

type Investment = {
  id: number;
  name: string;
  amount: number;
};

type Gain = Investment & { gain: number };
type Loss = Investment & { loss: number };

type Portfolio = {
  available: number;
  agent_open_investments: Investment[];
  agent_gains: Gain[];
  agent_losses: Loss[];
  manual_open_investments: Investment[];
  manual_gains: Gain[];
  manual_losses: Loss[];
};

type AgentStatus = {
  enabled: boolean;
  running: boolean;
  experiment_last_action: string | null;
  experiment_last_error: string | null;
  last_error: string | null;
  interval_seconds: number;
};

type LiveMatch = {
  id: number;
  league: string;
  home: string;
  away: string;
  home_goals: number | null;
  away_goals: number | null;
  minute: number | null;
};

type LiveResponse = {
  configured: boolean;
  matches: LiveMatch[];
  message: string;
  stale: boolean;
};

function money(value: number): string {
  return new Intl.NumberFormat("es-PE", {
    style: "currency",
    currency: "PEN",
  }).format(value);
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)} %`;
}

function dateInPeru(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("es-PE", {
    timeZone: "America/Lima",
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function choiceName(
  choice: Choice,
  home: string,
  away: string,
): string {
  if (choice === "H") return home;
  if (choice === "A") return away;
  return "Empate";
}

function betProbabilities(
  bet: Bet,
): Record<Choice, number> | null {
  if (
    bet.home_odds === null ||
    bet.draw_odds === null ||
    bet.away_odds === null
  ) {
    return null;
  }

  const inverse = {
    H: 1 / bet.home_odds,
    D: 1 / bet.draw_odds,
    A: 1 / bet.away_odds,
  };
  const total =
    inverse.H + inverse.D + inverse.A;

  return {
    H: inverse.H / total,
    D: inverse.D / total,
    A: inverse.A / total,
  };
}

function netResult(bet: Bet): string {
  if (bet.returned_amount === null) {
    return "Pendiente";
  }

  const difference =
    bet.returned_amount - bet.amount;

  return (
    `${difference >= 0 ? "+" : "−"}` +
    money(Math.abs(difference))
  );
}

function App() {
  const [experiment, setExperiment] =
    useState<Experiment | null>(null);
  const [portfolio, setPortfolio] =
    useState<Portfolio | null>(null);
  const [agent, setAgent] =
    useState<AgentStatus | null>(null);
  const [live, setLive] =
    useState<LiveResponse | null>(null);
  const [error, setError] = useState("");
  const [liveError, setLiveError] = useState("");
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] =
    useState<Date | null>(null);

  useEffect(() => {
    let active = true;
    let mainBusy = false;
    let liveBusy = false;

    async function updateMain() {
      if (mainBusy) return;
      mainBusy = true;

      try {
        const responses = await Promise.all([
          fetch("/api/live-paper"),
          fetch("/api/portfolio"),
          fetch("/api/agent/status"),
        ]);

        if (responses.some((response) => !response.ok)) {
          throw new Error(
            "No se pudo conectar con el backend.",
          );
        }

        const [bets, capital, status] =
          await Promise.all([
            responses[0].json() as Promise<Experiment>,
            responses[1].json() as Promise<Portfolio>,
            responses[2].json() as Promise<AgentStatus>,
          ]);

        if (active) {
          setExperiment(bets);
          setPortfolio(capital);
          setAgent(status);
          setUpdated(new Date());
          setError("");
        }
      } catch (problem) {
        if (active) {
          setError(
            problem instanceof Error
              ? problem.message
              : "No se pudieron cargar los datos.",
          );
        }
      } finally {
        mainBusy = false;
        if (active) setLoading(false);
      }
    }

    async function updateLive() {
      if (liveBusy) return;
      liveBusy = true;

      try {
        const response = await fetch(
          "/api/live-matches",
        );

        if (!response.ok) {
          throw new Error(
            "No se pudieron consultar marcadores.",
          );
        }

        const data =
          (await response.json()) as LiveResponse;

        if (active) {
          setLive(data);
          setLiveError("");
        }
      } catch (problem) {
        if (active) {
          setLiveError(
            problem instanceof Error
              ? problem.message
              : "Marcadores no disponibles.",
          );
        }
      } finally {
        liveBusy = false;
      }
    }

    void updateMain();
    void updateLive();

    const mainTimer = window.setInterval(
      () => void updateMain(),
      20_000,
    );
    const liveTimer = window.setInterval(
      () => void updateLive(),
      60_000,
    );

    return () => {
      active = false;
      window.clearInterval(mainTimer);
      window.clearInterval(liveTimer);
    };
  }, []);

  const bets = experiment?.bets ?? [];
  const archived = experiment?.archived_bets ?? [];
  const openBets = bets.filter(
    (bet) => bet.status === "abierta",
  );
  const closedBets = bets.filter(
    (bet) => bet.status !== "abierta",
  );

  const upcoming = [
    ...(experiment?.upcoming_matches ?? []),
  ]
    .filter(
      (match) =>
        Math.max(
          match.probabilities.H,
          match.probabilities.A,
        ) > 0.5,
    )
    .sort(
      (a, b) =>
        Math.max(
          b.probabilities.H,
          b.probabilities.A,
        ) -
        Math.max(
          a.probabilities.H,
          a.probabilities.A,
        ),
    )
    .slice(0, 10);

  return (
    <div className="dashboard">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#inicio">
            <span className="brand-mark">R</span>
            <span>
              <strong>Replikers</strong>
              <small>Panel de operaciones</small>
            </span>
          </a>

          <nav
            className="topnav"
            aria-label="Secciones"
          >
            <a href="#resumen">Resumen</a>
            <a href="#operaciones">Apuestas</a>
            <a href="#proximos">Próximos</a>
            <a href="#en-vivo">Marcadores</a>
          </nav>

          <span
            className={
              agent?.running
                ? "agent-badge working"
                : agent?.enabled
                  ? "agent-badge online"
                  : "agent-badge offline"
            }
          >
            <span className="status-dot" />
            {agent?.running
              ? "Analizando"
              : agent?.enabled
                ? "Agente activo"
                : "Agente detenido"}
          </span>
        </div>
      </header>

      <main className="page" id="inicio">
        <section className="page-intro" id="resumen">
          <div>
            <div className="eyebrow">
              CENTRO DE CONTROL · SIMULACIÓN
            </div>
            <h1>Apuestas ficticias</h1>
            <p>
              Partidos reales y selecciones
              experimentales con saldo ficticio.
            </p>
          </div>

          <div className="update-label">
            <span className="update-dot" />
            {updated
              ? `Actualizado ${updated.toLocaleTimeString(
                  "es-PE",
                  {
                    timeZone: "America/Lima",
                    hour: "2-digit",
                    minute: "2-digit",
                  },
                )}`
              : "Cargando"}
          </div>
        </section>

        {error && (
          <div className="alert error-alert">
            {error}
          </div>
        )}

        <section className="metrics">
          <article className="metric-card featured">
            <div className="metric-top">
              <span>Saldo disponible</span>
              <span className="metric-symbol">
                S/
              </span>
            </div>
            <strong>
              {experiment
                ? money(experiment.available)
                : "—"}
            </strong>
            <small>Dinero ficticio</small>
          </article>

          <article className="metric-card">
            <div className="metric-top">
              <span>En apuestas pendientes</span>
              <span className="metric-symbol">
                ↗
              </span>
            </div>
            <strong>
              {experiment
                ? money(experiment.invested)
                : "—"}
            </strong>
            <small>
              Incluye apuestas anteriores archivadas
            </small>
          </article>

          <article className="metric-card">
            <div className="metric-top">
              <span>Ganancia o pérdida neta</span>
              <span className="metric-symbol">
                ±
              </span>
            </div>
            <strong
              className={
                (experiment?.net ?? 0) < 0
                  ? "negative"
                  : "positive"
              }
            >
              {experiment
                ? money(experiment.net)
                : "—"}
            </strong>
            <small>
              Solo apuestas ya cerradas
            </small>
          </article>

          <article className="metric-card">
            <div className="metric-top">
              <span>Selecciones activas</span>
              <span className="metric-symbol">
                ◇
              </span>
            </div>
            <strong>{openBets.length} / 10</strong>
            <small>
              El agente repone lugares disponibles
            </small>
          </article>
        </section>

        <div className="main-grid">
          <section
            className="panel operations-panel"
            id="operaciones"
          >
            <div className="panel-heading">
              <div>
                <div className="section-kicker">
                  SELECCIÓN AUTOMÁTICA
                </div>
                <h2>Apuestas del agente</h2>
                <p>
                  Partidos próximos con probabilidad
                  implícita en cuotas superior al 50 %.
                </p>
              </div>

              <span className="count-pill">
                {bets.length} registradas
              </span>
            </div>

            {loading ? (
              <div className="empty-state">
                Cargando apuestas...
              </div>
            ) : bets.length === 0 ? (
              <div className="empty-state">
                No hay apuestas nuevas que cumplan
                el filtro y tengan cuotas disponibles.
              </div>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Partido</th>
                      <th>Selección</th>
                      <th>Probabilidades</th>
                      <th>Apuesta</th>
                      <th>Estado</th>
                      <th>Resultado</th>
                    </tr>
                  </thead>

                  <tbody>
                    {bets.map((bet) => {
                      const probabilities =
                        betProbabilities(bet);

                      return (
                        <tr key={bet.id}>
                          <td>
                            <strong>
                              {bet.home} vs{" "}
                              {bet.away}
                            </strong>
                            <span className="cell-sub">
                              {bet.league} ·{" "}
                              {bet.kickoff_utc
                                ? dateInPeru(
                                    bet.kickoff_utc,
                                  )
                                : bet.match_date}
                            </span>
                            <a
                              className="source-link"
                              href={bet.source_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Fuente
                            </a>
                          </td>

                          <td>
                            <strong>
                              {choiceName(
                                bet.selection,
                                bet.home,
                                bet.away,
                              )}
                            </strong>
                            <span className="cell-sub">
                              {bet.estimated_probability
                                !== null
                                ? `Cuota ajustada: ${percent(
                                    bet.estimated_probability,
                                  )}`
                                : "Sin porcentaje guardado"}
                            </span>
                          </td>

                          <td>
                            {probabilities ? (
                              <>
                                <strong>
                                  Local{" "}
                                  {percent(
                                    probabilities.H,
                                  )}
                                </strong>
                                <span className="cell-sub">
                                  Empate{" "}
                                  {percent(
                                    probabilities.D,
                                  )}
                                  {" · "}Visitante{" "}
                                  {percent(
                                    probabilities.A,
                                  )}
                                </span>
                              </>
                            ) : (
                              "No disponible"
                            )}
                          </td>

                          <td>
                            <strong>
                              {money(bet.amount)}
                            </strong>
                            <span className="cell-sub">
                              Cuota{" "}
                              {bet.odds.toFixed(2)}
                            </span>
                          </td>

                          <td>
                            <span
                              className={
                                `state-pill ${bet.status}`
                              }
                            >
                              {bet.status ===
                              "abierta"
                                ? "Pendiente"
                                : bet.status ===
                                    "ganada"
                                  ? "Ganada"
                                  : "Perdida"}
                            </span>
                          </td>

                          <td
                            className={
                              bet.status === "ganada"
                                ? "positive"
                                : bet.status ===
                                    "perdida"
                                  ? "negative"
                                  : ""
                            }
                          >
                            <strong>
                              {netResult(bet)}
                            </strong>
                            {bet.final_result && (
                              <span className="cell-sub">
                                Ganó:{" "}
                                {choiceName(
                                  bet.final_result,
                                  bet.home,
                                  bet.away,
                                )}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div className="panel-note">
              El porcentaje se deduce de cuotas
              ajustadas para sumar 100 %. No es una
              predicción validada ni asegura ganancias.
              Hay {archived.length} apuestas anteriores
              archivadas en la base de datos.
            </div>
          </section>

          <aside className="panel agent-panel">
            <div className="section-kicker">
              SUPERVISIÓN
            </div>
            <h2>Actividad del agente</h2>

            <div className="activity-item">
              <span className="activity-marker" />
              <div>
                <strong>
                  {agent?.running
                    ? "Revisando partidos"
                    : agent?.enabled
                      ? "Esperando siguiente ciclo"
                      : "Agente detenido"}
                </strong>
                <p>
                  Revisión cada{" "}
                  {Math.round(
                    (agent?.interval_seconds ??
                      3600) / 60,
                  )}{" "}
                  minutos.
                </p>
              </div>
            </div>

            <div className="activity-item">
              <span className="activity-marker muted" />
              <div>
                <strong>
                  Última acción
                </strong>
                <p>
                  {agent?.experiment_last_action ??
                    "Sin actividad reciente."}
                </p>
              </div>
            </div>

            {(agent?.last_error ||
              agent?.experiment_last_error) && (
              <div className="alert error-alert">
                {agent.experiment_last_error ??
                  agent.last_error}
              </div>
            )}
          </aside>
        </div>

        <section className="panel" id="proximos">
          <div className="panel-heading">
            <div>
              <div className="section-kicker">
                PRÓXIMAS HORAS
              </div>
              <h2>Diez favoritos disponibles</h2>
              <p>
                Horarios en Perú. Son candidatos;
                la tabla superior muestra las apuestas
                efectivamente registradas.
              </p>
            </div>
            <span className="count-pill">
              {upcoming.length} visibles
            </span>
          </div>

          {experiment?.upcoming_error ? (
            <div className="empty-state">
              {experiment.upcoming_error}
            </div>
          ) : upcoming.length === 0 ? (
            <div className="empty-state">
              No hay candidatos con cuotas disponibles
              en este momento.
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Inicio / liga</th>
                    <th>Partido</th>
                    <th>Local</th>
                    <th>Empate</th>
                    <th>Visitante</th>
                  </tr>
                </thead>
                <tbody>
                  {upcoming.map((match) => (
                    <tr key={match.fixture_id}>
                      <td>
                        <strong>
                          {dateInPeru(
                            match.kickoff_utc,
                          )}
                        </strong>
                        <span className="cell-sub">
                          {match.league}
                        </span>
                      </td>
                      <td>
                        <strong>
                          {match.home} vs{" "}
                          {match.away}
                        </strong>
                      </td>
                      <td>
                        {percent(
                          match.probabilities.H,
                        )}
                      </td>
                      <td>
                        {percent(
                          match.probabilities.D,
                        )}
                      </td>
                      <td>
                        {percent(
                          match.probabilities.A,
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section
          className="panel live-panel"
          id="en-vivo"
        >
          <div className="panel-heading">
            <div>
              <div className="section-kicker">
                MARCADORES
              </div>
              <h2>Partidos en juego</h2>
              <p>
                {live?.message ??
                  "Consultando marcadores..."}
              </p>
            </div>
            <span className="live-label">
              <span className="status-dot" />
              {live?.stale
                ? "SIN ACTUALIZAR"
                : "EN VIVO"}
            </span>
          </div>

          {liveError ? (
            <div className="empty-state">
              {liveError}
            </div>
          ) : live?.stale ? (
            <div className="empty-state">
              La fuente está temporalmente limitada.
              No mostramos marcadores antiguos como
              si fueran actuales.
            </div>
          ) : live && !live.configured ? (
            <div className="empty-state">
              Falta configurar API_SPORTS_KEY.
            </div>
          ) : live?.matches.length ? (
            <div className="live-list">
              {live.matches
                .slice(0, 12)
                .map((match) => (
                  <div
                    className="live-row"
                    key={match.id}
                  >
                    <div>
                      <span className="league-label">
                        {match.league}
                      </span>
                      <strong>
                        {match.home}
                        <span className="score">
                          {match.home_goals ??
                            "–"}
                          {" : "}
                          {match.away_goals ??
                            "–"}
                        </span>
                        {match.away}
                      </strong>
                    </div>
                    <span className="minute-pill">
                      {match.minute !== null
                        ? `${match.minute}′`
                        : "En juego"}
                    </span>
                  </div>
                ))}
            </div>
          ) : (
            <div className="empty-state">
              No hay partidos en juego disponibles.
            </div>
          )}
        </section>

        <section className="history-grid">
          <article className="panel">
            <div className="section-kicker">
              CAPITAL PRINCIPAL
            </div>
            <h2>Operaciones del agente</h2>
            <p className="section-description">
              Separadas de las apuestas ficticias.
            </p>
            <div className="mini-stats">
              <div>
                <span>Abiertas</span>
                <strong>
                  {portfolio
                    ?.agent_open_investments
                    .length ?? 0}
                </strong>
              </div>
              <div>
                <span>Ganancias</span>
                <strong className="positive">
                  {money(
                    portfolio?.agent_gains.reduce(
                      (sum, item) =>
                        sum + item.gain,
                      0,
                    ) ?? 0,
                  )}
                </strong>
              </div>
              <div>
                <span>Pérdidas</span>
                <strong className="negative">
                  {money(
                    portfolio?.agent_losses.reduce(
                      (sum, item) =>
                        sum + item.loss,
                      0,
                    ) ?? 0,
                  )}
                </strong>
              </div>
            </div>
          </article>

          <article className="panel">
            <div className="section-kicker">
              REGISTROS ANTERIORES
            </div>
            <h2>Pruebas manuales</h2>
            <p className="section-description">
              No pertenecen a la selección automática.
            </p>
            <div className="mini-stats">
              <div>
                <span>Abiertas</span>
                <strong>
                  {portfolio
                    ?.manual_open_investments
                    .length ?? 0}
                </strong>
              </div>
              <div>
                <span>Ganancias</span>
                <strong className="positive">
                  {money(
                    portfolio?.manual_gains.reduce(
                      (sum, item) =>
                        sum + item.gain,
                      0,
                    ) ?? 0,
                  )}
                </strong>
              </div>
              <div>
                <span>Pérdidas</span>
                <strong className="negative">
                  {money(
                    portfolio?.manual_losses.reduce(
                      (sum, item) =>
                        sum + item.loss,
                      0,
                    ) ?? 0,
                  )}
                </strong>
              </div>
            </div>
          </article>
        </section>

        <footer className="footer">
          <span>
            © Replikers · Simulación
          </span>
          <span>
            Dinero ficticio. Sin apuestas reales.
          </span>
          <span>
            {closedBets.length} apuestas nuevas
            cerradas
          </span>
        </footer>
      </main>
    </div>
  );
}

export default App;