"use client";

import {
  ArrowRight,
  Check,
  ChevronDown,
  Clipboard,
  Download,
  FileText,
  Mail,
  Play,
  Send,
  Star,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

/* ── types ── */

type Stage = "drop" | "configure" | "running" | "results";

/* ── constants ── */

type ProviderType = "anthropic" | "openai" | "proxy";

const PROVIDER_MODELS: Record<Exclude<ProviderType, "proxy">, { id: string; label: string }[]> = {
  anthropic: [
    { id: "claude-opus-4-8", label: "Claude Opus 4.8" },
    { id: "claude-opus-4-6", label: "Claude Opus 4.6" },
    { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
  ],
  openai: [
    { id: "gpt-5.5", label: "GPT-5.5" },
    { id: "gpt-5.5-pro", label: "GPT-5.5 Pro" },
    { id: "gpt-5.4", label: "GPT-5.4" },
    { id: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
  ],
};

const MOCK_RESULTS = [
  {
    firstName: "Maya",
    lastName: "Chen",
    company: "Northstar Labs",
    email: "maya@northstar.dev",
    subject: "Quick thought on Northstar\u2019s RevOps pipeline",
    body: "Hi Maya,\n\nI noticed Northstar Labs recently posted about helping RevOps teams spot stalled pipeline \u2014 that\u2019s a problem we hear about constantly from our B2B customers.\n\nWe built OpenCold to automate the outreach side of that equation: once your users identify a stuck deal, our tool generates research-backed follow-ups in seconds.\n\nWould it make sense to explore a quick integration? Happy to show you a 10-minute demo.\n\nBest,\nJane Smith",
    qualityWarnings: "",
  },
  {
    firstName: "Elliot",
    lastName: "Park",
    company: "Tandem API",
    email: "elliot@tandemapi.com",
    subject: "Saw your new API docs \u2014 partnership idea",
    body: "Hi Elliot,\n\nCongrats on the new API docs launch \u2014 the developer experience looks really polished. I\u2019m reaching out because Tandem\u2019s workflow APIs could be a great fit alongside what we\u2019re doing at OpenCold.\n\nWe help B2B teams automate personalized outreach using website research. A native Tandem integration could let your users trigger outreach sequences directly from their workflows.\n\nWorth a quick chat?\n\nBest,\nJane Smith",
    qualityWarnings: "",
  },
  {
    firstName: "Samira",
    lastName: "Ali",
    company: "Beacon CRM",
    email: "partners@beaconcrm.io",
    subject: "Partnership opportunity \u2014 OpenCold + Beacon CRM",
    body: "Hi Samira,\n\nI came across Beacon CRM\u2019s partner page and saw you\u2019re actively building out your agency ecosystem. We\u2019ve been working with similar B2B sales tools and think there\u2019s a natural fit.\n\nOpenCold auto-researches prospects and generates personalized emails \u2014 it could plug directly into Beacon\u2019s CRM workflows for your agency partners.\n\nWould love to explore this. Free for a 15-minute call this week?\n\nBest,\nJane Smith",
    qualityWarnings: "",
  },
  {
    firstName: "Jon",
    lastName: "Bell",
    company: "Ledgerflow",
    email: "jon@ledgerflow.co",
    subject: "Outreach idea for Ledgerflow\u2019s SMB push",
    body: "Hi Jon,\n\nI noticed Ledgerflow recently updated your pricing page with a focus on SMB finance teams. We\u2019re working on something complementary \u2014 OpenCold helps teams like yours reach the right prospects with emails grounded in real company research.\n\nGiven your product marketing focus, I thought you\u2019d appreciate seeing how we personalize at scale without sounding generic.\n\nHappy to send a quick demo video if that\u2019s easier?\n\nBest,\nJane Smith",
    qualityWarnings: "short_personalization",
  },
  {
    firstName: "Alex",
    lastName: "Torres",
    company: "SignalDesk",
    email: "alex@signaldesk.io",
    subject: "Helping SignalDesk teams close faster",
    body: "Hi Alex,\n\nSignalDesk\u2019s support ops dashboard caught my eye \u2014 especially the focus on fast-growing software teams. That\u2019s exactly the audience we serve with OpenCold.\n\nWe auto-research each prospect\u2019s website, find the right contact, and draft emails that reference real facts. It\u2019s been a game-changer for teams doing outbound alongside support-led growth.\n\nWould you be open to a quick call to see if there\u2019s a fit?\n\nBest,\nJane Smith",
    qualityWarnings: "",
  },
];

/* ── helpers ── */

function warningBadge(w: string) {
  if (!w) return null;
  const labels: Record<string, string> = {
    short_personalization: "Low personalization",
    generic_opener: "Generic opener",
    generation_failed: "Failed",
  };
  return (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
      {labels[w] || w}
    </span>
  );
}

function Counter({ value }: { value: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    let frame = 0;
    const total = 22;
    const id = window.setInterval(() => {
      frame++;
      setDisplay(Math.round((value * frame) / total));
      if (frame >= total) window.clearInterval(id);
    }, 18);
    return () => window.clearInterval(id);
  }, [value]);
  return <span className="font-semibold text-zinc-900">{display}</span>;
}

/* ── main page ── */

export default function Home() {
  const [stage, setStage] = useState<Stage>("drop");
  const [isDragging, setIsDragging] = useState(false);
  const [fileName, setFileName] = useState("");

  // configure — left: campaign (progressive expand)
  const [campaignTitle, setCampaignTitle] = useState("");
  const [campaignPitch, setCampaignPitch] = useState("");

  // configure — right sidebar accordions
  const [profileOpen, setProfileOpen] = useState(true);
  const [providerOpen, setProviderOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);

  // provider
  const [provider, setProvider] = useState<ProviderType>("anthropic");
  const [selectedModel, setSelectedModel] = useState("claude-opus-4-6");
  const [customModel, setCustomModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelDropOpen, setModelDropOpen] = useState(false);
  // proxy-specific
  const [proxyUrl, setProxyUrl] = useState("");
  const [proxyToken, setProxyToken] = useState("");
  const [proxyModel, setProxyModel] = useState("");

  // profile fields
  const [profileName, setProfileName] = useState("");
  const [profileCompany, setProfileCompany] = useState("");
  const [profileRole, setProfileRole] = useState("");
  const [profileBio, setProfileBio] = useState("");

  // template
  const [template, setTemplate] = useState("");

  // options
  const [findContacts, setFindContacts] = useState(true);
  const [requireVerified, setRequireVerified] = useState(false);

  // results
  const [openRow, setOpenRow] = useState<number | null>(0);
  const [smtpOpen, setSmtpOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);

  const hasCampaign = campaignTitle.trim().length > 0;
  const hasProfile = profileName.trim().length > 0;
  const canRun = hasCampaign && hasProfile;

  const effectiveModel =
    provider === "proxy"
      ? proxyModel || "\u2014"
      : selectedModel === "custom"
        ? customModel || "\u2014"
        : selectedModel;

  const switchProvider = (p: ProviderType) => {
    setProvider(p);
    setModelDropOpen(false);
    if (p === "anthropic") setSelectedModel("claude-opus-4-6");
    else if (p === "openai") setSelectedModel("gpt-5.5");
    else setSelectedModel("");
  };

  const startConfigure = (name = "companies.csv") => {
    setFileName(name);
    setStage("configure");
  };

  const startRun = () => {
    setStage("running");
    window.setTimeout(() => setStage("results"), 1400);
  };

  return (
    <main className="relative min-h-screen bg-white text-zinc-900">
      {/* dot background */}
      <div
        className={`dot-field ${stage !== "drop" ? "dot-field--fade" : ""}`}
      />

      {/* header */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <button
          className="text-[15px] font-semibold tracking-tight"
          onClick={() => setStage("drop")}
        >
          opencold
        </button>
        <a
          href="https://github.com/mhttekin/opencold"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-600 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
        >
          <svg
            viewBox="0 0 16 16"
            width={14}
            height={14}
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
          Star
          <Star size={11} className="fill-amber-400 text-amber-400" />
        </a>
      </header>

      {/* ── STAGE: DROP ── */}
      {stage === "drop" && (
        <section className="relative z-10 mx-auto flex min-h-[calc(100vh-80px)] max-w-2xl flex-col items-center justify-center px-6">
          <h1 className="text-center text-[clamp(2rem,5vw,3.2rem)] font-semibold leading-[1.1] tracking-tight">
            Cold outreach,
            <br />
            grounded in research.
          </h1>
          <p className="mt-4 max-w-md text-center text-[15px] leading-relaxed text-zinc-500">
            Drop a CSV of companies. OpenCold reads their websites, finds the
            right contacts, and writes emails that reference real facts.
          </p>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              startConfigure(e.dataTransfer.files[0]?.name || "companies.csv");
            }}
            onClick={() => fileRef.current?.click()}
            className={`drop-zone mt-10 w-full max-w-lg ${isDragging ? "drop-zone--active" : ""}`}
          >
            <div className="flex flex-col items-center px-6 text-center">
              <div className="mb-4 grid size-11 place-items-center rounded-full bg-zinc-900 text-white">
                <FileText size={20} />
              </div>
              <p className="text-lg font-medium">Drop your CSV here</p>
              <p className="mt-1.5 text-sm text-zinc-400">or click to browse</p>
            </div>
            <input
              ref={fileRef}
              className="hidden"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) =>
                startConfigure(e.target.files?.[0]?.name || "companies.csv")
              }
            />
          </div>

          {/* csv ghost */}
          <div className="mt-8 w-full max-w-sm opacity-40" aria-hidden="true">
            <div className="csv-sheet">
              <div className="csv-header">
                <span>Name</span>
                <span>Company</span>
                <span>Website</span>
              </div>
              <div className="csv-row csv-row--one" />
              <div className="csv-row csv-row--two" />
              <div className="csv-row csv-row--three" />
            </div>
          </div>

          <div className="mt-4 flex gap-2">
            {["Name", "Company", "Website URL"].map((label) => (
              <span
                key={label}
                className="rounded-full border border-zinc-200 px-3 py-1 text-[11px] font-medium text-zinc-400"
              >
                {label}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* ── STAGE: CONFIGURE ── */}
      {stage === "configure" && (
        <section className="configure-enter relative z-10 mx-auto max-w-5xl px-6 pb-20 pt-6 sm:pt-10">
          {/* top bar — file indicator + run button */}
          <div className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid size-7 place-items-center rounded-lg bg-zinc-100">
                <Check size={14} className="text-zinc-500" />
              </div>
              <div>
                <p className="text-sm font-medium">{fileName}</p>
                <p className="text-xs text-zinc-400">Ready to configure</p>
              </div>
            </div>
            <button
              disabled={!canRun}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-900 px-5 text-sm font-medium text-white transition disabled:opacity-30 active:scale-[0.97]"
              onClick={startRun}
            >
              <Play size={14} />
              Run
            </button>
          </div>

          {/* two-column layout */}
          <div className="grid items-start gap-8 lg:grid-cols-[1fr_340px]">
            {/* ── LEFT: sections ── */}
            <div className="space-y-10">
              {/* Section 1: Campaign */}
              <div className="config-section">
                <div className="config-section-header">
                  <span className="config-step-number">1</span>
                  <div>
                    <h2 className="text-[15px] font-semibold tracking-tight">
                      Campaign
                    </h2>
                    <p className="mt-0.5 text-sm text-zinc-400">
                      Give this run a name and describe your outreach goal.
                    </p>
                  </div>
                </div>
                <div className="mt-5 space-y-3">
                  <label className="block text-xs font-medium text-zinc-500">
                    Campaign title
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 bg-white px-4 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={campaignTitle}
                      onChange={(e) => setCampaignTitle(e.target.value)}
                      placeholder="e.g. Q3 DevTool partnerships"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    What&apos;s the pitch or purpose of this outreach?
                    <textarea
                      className="mt-1.5 min-h-[72px] w-full resize-y rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={campaignPitch}
                      onChange={(e) => setCampaignPitch(e.target.value)}
                      placeholder="e.g. We help B2B teams automate outreach — looking to partner with dev tool companies..."
                    />
                  </label>
                </div>
              </div>

              {/* Section 2: Ready to run — expands when Campaign is filled */}
              <div
                className="accordion-body"
                style={{ gridTemplateRows: hasCampaign ? "1fr" : "0fr" }}
              >
                <div className="min-h-0 overflow-hidden">
                  <div className="config-section" style={{ borderBottom: "none" }}>
                    <div className="config-section-header">
                      <span className="config-step-number">2</span>
                      <div>
                        <h2 className="text-[15px] font-semibold tracking-tight">
                          Ready to run
                        </h2>
                        <p className="mt-0.5 text-sm text-zinc-400">
                          We&apos;ll scan each company&apos;s website, find the
                          right contact, and generate personalized emails.
                        </p>
                      </div>
                    </div>
                    <div className="mt-5">
                      <button
                        disabled={!canRun}
                        className="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-900 px-6 text-sm font-medium text-white transition disabled:opacity-30 active:scale-[0.97]"
                        onClick={startRun}
                      >
                        <Play size={14} />
                        Run opencold
                        <ArrowRight size={14} />
                      </button>
                      {!hasProfile && hasCampaign && (
                        <p className="mt-3 text-xs text-zinc-400">
                          Fill in your{" "}
                          <button
                            className="underline hover:text-zinc-900"
                            onClick={() => setProfileOpen(true)}
                          >
                            Profile
                          </button>{" "}
                          to continue.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* ── RIGHT: sidebar accordions ── */}
            <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start">
              {/* Profile accordion */}
              <Accordion
                title="Profile"
                badge="required"
                open={profileOpen}
                onToggle={() => setProfileOpen(!profileOpen)}
                filled={hasProfile}
              >
                <div className="space-y-3">
                  <label className="block text-xs font-medium text-zinc-500">
                    Your name
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      placeholder="Jane Smith"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    Company
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileCompany}
                      onChange={(e) => setProfileCompany(e.target.value)}
                      placeholder="Acme Inc"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    Role
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileRole}
                      onChange={(e) => setProfileRole(e.target.value)}
                      placeholder="Growth Lead"
                    />
                  </label>
                  <label className="block text-xs font-medium text-zinc-500">
                    What you do / offer
                    <textarea
                      className="mt-1.5 min-h-[72px] w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={profileBio}
                      onChange={(e) => setProfileBio(e.target.value)}
                      placeholder="We help B2B teams automate outreach..."
                    />
                  </label>
                </div>
              </Accordion>

              {/* Template accordion */}
              <Accordion
                title="Template"
                open={templateOpen}
                onToggle={() => setTemplateOpen(!templateOpen)}
                filled={template.trim().length > 0}
              >
                <label className="block text-xs font-medium text-zinc-500">
                  Custom email template
                  <textarea
                    className="mt-1.5 min-h-[120px] w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                    value={template}
                    onChange={(e) => setTemplate(e.target.value)}
                    placeholder={"Hi {first_name},\n\nI noticed {fact}...\n\nBest,\n{sender_name}"}
                  />
                </label>
                <p className="mt-2 text-[11px] text-zinc-400">
                  Variables: {"{first_name}"}, {"{company}"}, {"{fact}"},{" "}
                  {"{sender_name}"}
                </p>
              </Accordion>

              {/* Provider accordion */}
              <Accordion
                title="Provider"
                badge="required"
                open={providerOpen}
                onToggle={() => setProviderOpen(!providerOpen)}
                filled={provider === "proxy" ? proxyUrl.length > 0 : apiKey.length > 0}
              >
                <div className="space-y-3">
                  {/* provider tabs */}
                  <div className="flex gap-0.5 rounded-md bg-zinc-100 p-0.5">
                    {(["anthropic", "openai", "proxy"] as const).map((p) => (
                      <button
                        key={p}
                        className={`flex-1 rounded px-2 py-1 text-[11px] font-semibold tracking-wide transition ${
                          provider === p
                            ? "bg-white text-zinc-900 shadow-sm"
                            : "text-zinc-400 hover:text-zinc-600"
                        }`}
                        onClick={() => switchProvider(p)}
                      >
                        {p === "anthropic" ? "Anthropic" : p === "openai" ? "OpenAI" : "Proxy"}
                      </button>
                    ))}
                  </div>

                  {/* API key — all providers */}
                  <label className="block text-[11px] font-medium text-zinc-400">
                    API key
                    <input
                      type="password"
                      className="mt-1 h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      value={provider === "proxy" ? proxyToken : apiKey}
                      onChange={(e) =>
                        provider === "proxy"
                          ? setProxyToken(e.target.value)
                          : setApiKey(e.target.value)
                      }
                      placeholder={
                        provider === "anthropic"
                          ? "sk-ant-..."
                          : provider === "openai"
                            ? "sk-..."
                            : "Bearer token"
                      }
                    />
                  </label>

                  {provider !== "proxy" ? (
                    <>
                      {/* model — click to expand inline list */}
                      <div>
                        <span className="mb-1 block text-[11px] font-medium text-zinc-400">Model</span>
                        <button
                          className="flex h-9 w-full items-center justify-between rounded-lg border border-zinc-200 px-3 text-xs transition hover:border-zinc-400"
                          onClick={() => setModelDropOpen(!modelDropOpen)}
                        >
                          <span className="font-medium text-zinc-900">
                            {selectedModel === "custom"
                              ? customModel || "Custom"
                              : PROVIDER_MODELS[provider].find((m) => m.id === selectedModel)?.label ?? selectedModel}
                          </span>
                          <ChevronDown
                            size={12}
                            className={`text-zinc-400 transition-transform ${modelDropOpen ? "rotate-180" : ""}`}
                          />
                        </button>

                        {/* inline options */}
                        <div
                          className="accordion-body mt-1"
                          style={{ gridTemplateRows: modelDropOpen ? "1fr" : "0fr" }}
                        >
                          <div className="min-h-0 overflow-hidden">
                            <div className="space-y-0.5 rounded-lg border border-zinc-100 bg-zinc-50/60 p-1">
                              {PROVIDER_MODELS[provider].map((m) => (
                                <button
                                  key={m.id}
                                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition ${
                                    selectedModel === m.id
                                      ? "bg-white shadow-sm"
                                      : "hover:bg-white/60"
                                  }`}
                                  onClick={() => {
                                    setSelectedModel(m.id);
                                    setCustomModel("");
                                    setModelDropOpen(false);
                                  }}
                                >
                                  <span className={`font-medium ${selectedModel === m.id ? "text-zinc-900" : "text-zinc-600"}`}>
                                    {m.label}
                                  </span>
                                  <span className="ml-auto font-mono text-[10px] text-zinc-400">
                                    {m.id}
                                  </span>
                                </button>
                              ))}
                              <button
                                className={`flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-xs transition ${
                                  selectedModel === "custom"
                                    ? "bg-white shadow-sm"
                                    : "hover:bg-white/60"
                                }`}
                                onClick={() => {
                                  setSelectedModel("custom");
                                  setModelDropOpen(false);
                                }}
                              >
                                <span className={`font-medium ${selectedModel === "custom" ? "text-zinc-900" : "text-zinc-600"}`}>
                                  Custom...
                                </span>
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>

                      {selectedModel === "custom" && (
                        <input
                          className="h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                          value={customModel}
                          onChange={(e) => setCustomModel(e.target.value)}
                          placeholder="Custom model ID"
                          autoFocus
                        />
                      )}
                    </>
                  ) : (
                    <>
                      <label className="block text-[11px] font-medium text-zinc-400">
                        Router URL
                        <input
                          className="mt-1 h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                          value={proxyUrl}
                          onChange={(e) => setProxyUrl(e.target.value)}
                          placeholder="https://your-proxy.example.com/v1"
                        />
                      </label>
                      <label className="block text-[11px] font-medium text-zinc-400">
                        Model name
                        <input
                          className="mt-1 h-9 w-full rounded-lg border border-zinc-200 px-3 text-xs font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                          value={proxyModel}
                          onChange={(e) => setProxyModel(e.target.value)}
                          placeholder="e.g. llama-3.1-70b"
                        />
                      </label>
                    </>
                  )}
                </div>
              </Accordion>

              {/* Options accordion */}
              <Accordion
                title="Options"
                open={optionsOpen}
                onToggle={() => setOptionsOpen(!optionsOpen)}
              >
                <div className="space-y-4">
                  <SidebarToggle
                    label="Find contact emails"
                    description="MX + SMTP verification"
                    checked={findContacts}
                    onChange={setFindContacts}
                  />
                  <SidebarToggle
                    label="Verified emails only"
                    description="Filter out unverified rows"
                    checked={requireVerified}
                    onChange={setRequireVerified}
                  />
                </div>
              </Accordion>

              {/* run summary */}
              <div className="rounded-xl border border-zinc-100 bg-zinc-50/50 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Run summary
                </h3>
                <dl className="mt-4 space-y-3 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">File</dt>
                    <dd className="font-medium">{fileName}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Campaign</dt>
                    <dd className="max-w-[160px] truncate text-right font-medium">
                      {campaignTitle || "\u2014"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Profile</dt>
                    <dd className="font-medium">
                      {profileName || "\u2014"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Model</dt>
                    <dd className="max-w-[160px] truncate text-right font-mono text-xs font-medium">
                      {effectiveModel}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-zinc-400">Email lookup</dt>
                    <dd className="font-medium">
                      {findContacts ? "On" : "Off"}
                    </dd>
                  </div>
                </dl>
              </div>
            </aside>
          </div>
        </section>
      )}

      {/* ── STAGE: RUNNING ── */}
      {stage === "running" && (
        <section className="configure-enter relative z-10 mx-auto max-w-3xl px-6 pb-20 pt-8 sm:pt-16">
          <h2 className="text-2xl font-semibold tracking-tight">Running...</h2>
          <p className="mt-2 text-sm text-zinc-400">
            Researching websites and generating personalized emails.
          </p>
          <SkeletonTable />
        </section>
      )}

      {/* ── STAGE: RESULTS ── */}
      {stage === "results" && (
        <section className="configure-enter relative z-10 mx-auto max-w-4xl px-6 pb-20 pt-8 sm:pt-16">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Generated emails
              </h2>
              <p className="mt-1 text-sm text-zinc-400">
                {fileName} &middot; {MOCK_RESULTS.length} emails generated
              </p>
            </div>
            <div className="flex gap-2">
              <button className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-900 px-4 text-sm font-medium text-white transition active:scale-[0.97]">
                <Download size={15} />
                Download CSV
              </button>
              <button
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-200 px-4 text-sm font-medium text-zinc-700 transition hover:border-zinc-400 active:scale-[0.97]"
                onClick={() => setSmtpOpen(true)}
              >
                <Mail size={15} />
                Send via SMTP
              </button>
              <button
                className="grid size-9 place-items-center rounded-lg border border-zinc-200 text-zinc-400 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]"
                aria-label="Copy to clipboard"
              >
                <Clipboard size={15} />
              </button>
            </div>
          </div>

          <div className="stats-row mt-4 border-b border-zinc-100 pb-4">
            <span>
              <Counter value={MOCK_RESULTS.length} /> emails
            </span>
            <span>
              <Counter
                value={
                  MOCK_RESULTS.filter((r) => !r.qualityWarnings).length
                }
              />{" "}
              clean
            </span>
            <span>
              <Counter
                value={
                  MOCK_RESULTS.filter((r) => r.qualityWarnings).length
                }
              />{" "}
              warnings
            </span>
          </div>

          <div className="mt-6 space-y-3">
            {MOCK_RESULTS.map((row, i) => (
              <div
                key={row.email}
                className={`result-row rounded-xl border border-zinc-100 overflow-hidden ${openRow === i ? "result-row--open" : ""}`}
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <button
                  className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-zinc-50"
                  onClick={() => setOpenRow(openRow === i ? null : i)}
                >
                  <span className={`size-2 flex-shrink-0 rounded-full ${row.qualityWarnings ? "bg-amber-400" : "bg-emerald-500"}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold truncate">
                      {row.subject}
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-400">
                      To: {row.firstName} {row.lastName} &lt;{row.email}&gt;
                      {" "}&middot;{" "}{row.company}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {row.qualityWarnings && warningBadge(row.qualityWarnings)}
                    <ChevronDown
                      size={14}
                      className={`text-zinc-400 transition-transform ${openRow === i ? "rotate-180" : ""}`}
                    />
                  </div>
                </button>
                <div className="result-detail">
                  <div className="min-h-0">
                    <div className="border-t border-zinc-100 px-5 py-5">
                      <div className="flex items-center gap-2 text-xs text-zinc-400">
                        <Mail size={12} />
                        <span>Subject: <span className="font-medium text-zinc-600">{row.subject}</span></span>
                      </div>
                      <pre className="mt-4 whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-700">
                        {row.body}
                      </pre>
                      <div className="mt-4 flex gap-2">
                        <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-500 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]">
                          <Clipboard size={12} />
                          Copy
                        </button>
                        <button className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-zinc-200 px-3 text-xs font-medium text-zinc-500 transition hover:border-zinc-400 hover:text-zinc-900 active:scale-[0.97]">
                          <Send size={12} />
                          Send
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── SMTP drawer ── */}
      {smtpOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/15 backdrop-blur-[2px]"
          onClick={() => setSmtpOpen(false)}
        >
          <aside
            className="absolute right-0 top-0 h-full w-full max-w-md border-l border-zinc-100 bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold tracking-tight">
                SMTP setup
              </h2>
              <button
                className="grid size-8 place-items-center rounded-lg border border-zinc-200 text-zinc-400 transition hover:text-zinc-900 active:scale-[0.97]"
                onClick={() => setSmtpOpen(false)}
                aria-label="Close"
              >
                <X size={15} />
              </button>
            </div>
            <div className="mt-6 grid gap-4">
              {["Host", "Port", "User", "Password", "From address"].map(
                (label) => (
                  <label
                    key={label}
                    className="text-xs font-medium text-zinc-500"
                  >
                    {label}
                    <input
                      className="mt-1.5 h-10 w-full rounded-lg border border-zinc-200 px-3 text-sm font-normal text-zinc-900 outline-none transition placeholder:text-zinc-300 focus:border-zinc-900"
                      placeholder={label === "Port" ? "587" : ""}
                      type={label === "Password" ? "password" : "text"}
                    />
                  </label>
                ),
              )}
            </div>
            <button className="mt-5 h-10 w-full rounded-lg border border-zinc-200 text-sm font-medium transition hover:border-zinc-400 active:scale-[0.97]">
              Test connection
            </button>
            <button
              className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-zinc-900 text-sm font-medium text-white transition active:scale-[0.97]"
              onClick={() => setConfirmOpen(true)}
            >
              <Send size={15} />
              Send all
            </button>
          </aside>
        </div>
      )}

      {/* ── confirm dialog ── */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/20 backdrop-blur-[2px] p-5">
          <div className="w-full max-w-sm rounded-xl border border-zinc-100 bg-white p-6 shadow-2xl">
            <h2 className="text-lg font-semibold tracking-tight">
              Send 4 emails?
            </h2>
            <p className="mt-2 text-sm text-zinc-400">
              One row has no verified email and will be skipped.
            </p>
            <div className="mt-6 grid grid-cols-2 gap-3">
              <button
                className="h-9 rounded-lg border border-zinc-200 text-sm font-medium active:scale-[0.97]"
                onClick={() => setConfirmOpen(false)}
              >
                Cancel
              </button>
              <button className="h-9 rounded-lg bg-zinc-900 text-sm font-medium text-white active:scale-[0.97]">
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

/* ── components ── */

function Accordion({
  title,
  badge,
  open,
  onToggle,
  filled,
  children,
}: {
  title: string;
  badge?: string;
  open: boolean;
  onToggle: () => void;
  filled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-100 bg-zinc-50/50 overflow-hidden">
      <button
        className="flex w-full items-center justify-between px-5 py-4 text-left"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2">
          {filled && (
            <span className="grid size-4 place-items-center rounded-full bg-zinc-900">
              <Check size={10} className="text-white" />
            </span>
          )}
          <span className="text-sm font-semibold text-zinc-700">{title}</span>
          {badge && (
            <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[10px] font-medium text-zinc-500">
              {badge}
            </span>
          )}
        </div>
        <ChevronDown
          size={14}
          className={`text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      <div
        className="accordion-body"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="px-5 pb-5">{children}</div>
        </div>
      </div>
    </div>
  );
}

function SidebarToggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      className="flex w-full items-center justify-between gap-3 text-left"
      onClick={() => onChange(!checked)}
    >
      <div>
        <p className="text-sm font-medium text-zinc-700">{label}</p>
        <p className="text-xs text-zinc-400">{description}</p>
      </div>
      <span className={`toggle-track ${checked ? "toggle-track--on" : ""}`}>
        <span className="toggle-thumb" />
      </span>
    </button>
  );
}

function SkeletonTable() {
  return (
    <div className="mt-6 space-y-3">
      {[0, 1, 2, 3, 4].map((row) => (
        <div
          key={row}
          className="rounded-xl border border-zinc-100 px-5 py-4"
          style={{ animationDelay: `${row * 120}ms` }}
        >
          <div className="flex items-center gap-4">
            <span className="size-2 rounded-full bg-zinc-200 skeleton" />
            <div className="flex-1 space-y-2">
              <span className="block h-3.5 w-3/5 rounded-full bg-zinc-100 skeleton" />
              <span className="block h-2.5 w-2/5 rounded-full bg-zinc-50 skeleton" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
