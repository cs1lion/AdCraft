import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import { demoProjects, images, imageSrc } from "../data";
import type { ProjectV2Summary } from "../types-v2";
import { DiscoverOrbit, type DiscoverOrbitItem } from "./DiscoverOrbit";

const homeProductPoster = "/assets/card1.webp";
const heroTitleLines = [
  "ONE SENTENCE",
  "BECOMES AN",
  "Ad film.",
] as const;
const discoverCards: readonly DiscoverOrbitItem[] = [
  { title: "Campaign Flow", image: imageSrc(images[0]) },
  { title: "Character Study", image: imageSrc(images[1]) },
  { title: "Poster Motion", image: imageSrc(images[2]) },
  { title: "Scene Extension", image: imageSrc(images[3]) },
  { title: "Product Aura", image: imageSrc(images[4]) },
  { title: "Editorial Cut", image: imageSrc(images[5]) },
  { title: "Portrait Spark", image: imageSrc(images[6]) },
  { title: "Color Script", image: imageSrc(images[7]) },
];

type RevealState = "pending" | "visible";

type RevealSection = {
  sectionRef?: RefObject<HTMLElement | null>;
  revealState?: RevealState;
};

type HomeShowcaseInteractions = {
  createProject: () => void;
  openWorkflow: () => void;
  openProject: (projectId: string, workflowId: string) => void;
  openPreview: () => void;
  closePreview: () => void;
};

export type HomeShowcaseProps = {
  mode: "interactive" | "static";
  interactions?: HomeShowcaseInteractions;
  heroMotionReady?: boolean;
  recentReveal?: RevealSection;
  discoverReveal?: RevealSection;
  hasIntroVideo?: boolean;
  productVideoUrl?: string;
  onProductVideoError?: () => void;
  previewOpen?: boolean;
  recentProjects?: ProjectV2Summary[];
  activeProjectId?: string | null;
};

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="section-title">
      <h2 data-home-typography-region="sectionHeading">{title}</h2>
      <p data-home-typography-region="sectionBody">{subtitle}</p>
    </div>
  );
}

function motionStyle(property: "--home-reveal-delay", value: string): CSSProperties {
  return { [property]: value } as CSSProperties;
}

type HeroQueueCharacter = {
  characterIndex: number;
  motionOrder: number;
  slotIndex: number;
};

type HeroQueueDirection = "from-left" | "from-right";

function createHeroQueueCharacters(
  line: string,
  direction: HeroQueueDirection,
): HeroQueueCharacter[] {
  const characters = Array.from(line);
  const motionOrderByCharacterIndex = new Map<number, number>();
  let motionOrder = 0;

  const startIndex = direction === "from-left" ? characters.length - 1 : 0;
  const endIndex = direction === "from-left" ? -1 : characters.length;
  const step = direction === "from-left" ? -1 : 1;
  for (
    let characterIndex = startIndex;
    characterIndex !== endIndex;
    characterIndex += step
  ) {
    if (characters[characterIndex] !== " ") {
      motionOrderByCharacterIndex.set(characterIndex, motionOrder);
      motionOrder += 1;
    }
  }

  let slotIndex = 0;
  return characters.flatMap((character, characterIndex) => {
    if (character === " ") return [];

    const queueCharacter: HeroQueueCharacter = {
      characterIndex,
      motionOrder: motionOrderByCharacterIndex.get(characterIndex) ?? 0,
      slotIndex,
    };
    slotIndex += 1;
    return [queueCharacter];
  });
}

function useHeroQueueStartOffsets(
  lineRef: RefObject<HTMLSpanElement | null>,
  characterRefs: RefObject<(HTMLSpanElement | null)[]>,
  characterCount: number,
  direction: HeroQueueDirection,
) {
  const [startOffsets, setStartOffsets] = useState<number[]>([]);

  const measure = useCallback(() => {
    const line = lineRef.current;
    if (!line) return;

    const lineRect = line.getBoundingClientRect();
    const origin = direction === "from-left" ? lineRect.left : lineRect.right;
    const nextOffsets = Array.from({ length: characterCount }, (_, slotIndex) => {
      const character = characterRefs.current[slotIndex];
      if (!character) return null;

      const characterRect = character.getBoundingClientRect();
      return direction === "from-left"
        ? origin - characterRect.left
        : origin - characterRect.right;
    });
    if (nextOffsets.some((offset) => offset === null)) return;

    const measuredOffsets = nextOffsets as number[];
    setStartOffsets((previousOffsets) => {
      const hasChanged = previousOffsets.length !== measuredOffsets.length
        || previousOffsets.some((offset, index) => Math.abs(offset - measuredOffsets[index]!) > 0.1);
      return hasChanged ? measuredOffsets : previousOffsets;
    });
  }, [characterCount, characterRefs, direction, lineRef]);

  useLayoutEffect(() => {
    const line = lineRef.current;
    if (!line) return;

    measure();
    const resizeObserver = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(measure);
    resizeObserver?.observe(line);
    window.addEventListener("resize", measure);

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [lineRef, measure]);

  return startOffsets;
}

function heroCharacterStyle(
  motionOrder: number,
  startOffset: number | undefined,
): CSSProperties {
  return {
    "--home-hero-character-index": String(motionOrder),
    "--home-hero-character-start-offset": `${startOffset ?? 0}px`,
  } as CSSProperties;
}

function HeroMainTitleLine({ line, direction }: { line: string; direction: HeroQueueDirection }) {
  const characters = Array.from(line);
  const queueCharacters = createHeroQueueCharacters(line, direction);
  const queueCharacterByIndex = new Map(
    queueCharacters.map((queueCharacter) => [queueCharacter.characterIndex, queueCharacter]),
  );
  const lineRef = useRef<HTMLSpanElement>(null);
  const characterRefs = useRef<(HTMLSpanElement | null)[]>([]);
  const startOffsets = useHeroQueueStartOffsets(
    lineRef,
    characterRefs,
    queueCharacters.length,
    direction,
  );
  const isQueueReady = startOffsets.length === queueCharacters.length;

  return (
    <span
      ref={lineRef}
      className="hero__line hero__line--queue"
      data-home-hero-queue-origin={direction === "from-left" ? "line-start" : "line-end"}
      data-home-hero-queue-ready={isQueueReady ? "true" : "false"}
      aria-hidden="true"
    >
      {characters.map((character, characterIndex) => {
        if (character === " ") return "\u00a0";

        const queueCharacter = queueCharacterByIndex.get(characterIndex);
        if (!queueCharacter) return null;

        return (
          <span
            key={`${character}-${characterIndex}`}
            ref={(element) => {
              characterRefs.current[queueCharacter.slotIndex] = element;
            }}
            className="hero__char"
            data-home-hero-character-order={queueCharacter.motionOrder}
            style={heroCharacterStyle(
              queueCharacter.motionOrder,
              startOffsets[queueCharacter.slotIndex],
            )}
          >
            <span className="hero__glyph">{character}</span>
          </span>
        );
      })}
    </span>
  );
}

function HeroTitle() {
  return (
    <h1
      className="hero__title"
      id="home-product-title"
      aria-label="One Sentence Becomes an Ad film."
      data-home-typography-region="heroMain"
    >
      <HeroMainTitleLine line={heroTitleLines[0]} direction="from-left" />
      <HeroMainTitleLine line={heroTitleLines[1]} direction="from-right" />
      <span
        className="hero__line hero__accent"
        data-accent-text={heroTitleLines[2]}
        data-home-hero-accent-reveal="diagonal"
        data-home-typography-region="heroAccent"
        data-testid="home-hero-accent"
        aria-hidden="true"
      >
        {heroTitleLines[2]}
      </span>
    </h1>
  );
}

function CreateProjectButtonContent() {
  return (
    <>
      <svg
        className="hero__icon"
        aria-hidden="true"
        viewBox="0 0 256 256"
      >
        <path d="M220,128a4,4,0,0,1-4,4H132v84a4,4,0,0,1-8,0V132H40a4,4,0,0,1,0-8h84V40a4,4,0,0,1,8,0v84h84A4,4,0,0,1,220,128Z" />
      </svg>
      <span>Create Your Project</span>
    </>
  );
}

function formatRelativeTime(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Updated today";
  if (diffDays === 1) return "Updated yesterday";
  if (diffDays < 7) return `Updated ${diffDays} days ago`;
  if (diffDays < 30) return `Updated ${Math.floor(diffDays / 7)} weeks ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function InteractiveRecentCards({
  openWorkflow,
  openProject,
  recentProjects,
  activeProjectId,
}: {
  openWorkflow: () => void;
  openProject: (projectId: string, workflowId: string) => void;
  recentProjects: ProjectV2Summary[];
  activeProjectId: string | null;
}) {
  const sortedProjects = [...recentProjects]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 3);

  const activeProject = activeProjectId
    ? recentProjects.find((p) => p.project_id === activeProjectId) ?? null
    : null;

  const featuredTitle = activeProject ? activeProject.name : "New fragrance product reel";
  const featuredSubtitle = activeProject
    ? "Continue editing this project."
    : "Continue editing the current workflow canvas.";
  const featuredOnClick = activeProject
    ? () => openProject(activeProject.project_id, activeProject.workflow_id)
    : openWorkflow;

  return (
    <div className="recent-strip" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
      <button
        className="recent featured"
        data-reveal-item
        style={motionStyle("--home-reveal-delay", "170ms")}
        onClick={featuredOnClick}
      >
        <div className="featured-glass">
          <h3 data-home-typography-region="cardTitle">{featuredTitle}</h3>
          <p data-home-typography-region="cardMeta">{featuredSubtitle}</p>
        </div>
      </button>
      {sortedProjects.map((project, index) => (
        <button
          key={project.project_id}
          className="recent"
          data-reveal-item
          style={motionStyle("--home-reveal-delay", `${240 + index * 70}ms`)}
          onClick={() => openProject(project.project_id, project.workflow_id)}
        >
          <h3 data-home-typography-region="cardTitle">{project.name}</h3>
          <p data-home-typography-region="cardMeta">{formatRelativeTime(project.updated_at)}</p>
        </button>
      ))}
    </div>
  );
}

function StaticRecentCards() {
  return (
    <div className="recent-strip" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
      <article className="recent featured" data-reveal-item style={motionStyle("--home-reveal-delay", "170ms")}>
        <div className="featured-glass">
          <h3 data-home-typography-region="cardTitle">New fragrance product reel</h3>
          <p data-home-typography-region="cardMeta">Continue editing the current workflow canvas.</p>
        </div>
      </article>
      {demoProjects.slice(0, 3).map((project, index) => (
        <article
          key={project.name}
          className="recent"
          data-reveal-item
          style={motionStyle("--home-reveal-delay", `${240 + index * 70}ms`)}
        >
          <h3 data-home-typography-region="cardTitle">{project.name}</h3>
          <p data-home-typography-region="cardMeta">{project.time}</p>
        </article>
      ))}
    </div>
  );
}

function InteractiveDiscover({ openPreview }: { openPreview: () => void }) {
  return <DiscoverOrbit items={discoverCards} interactive onSelect={openPreview} />;
}

function StaticDiscover() {
  return <DiscoverOrbit items={discoverCards} interactive={false} />;
}

export function HomeShowcase({
  mode,
  interactions,
  heroMotionReady = false,
  recentReveal,
  discoverReveal,
  hasIntroVideo = false,
  productVideoUrl,
  onProductVideoError,
  previewOpen = false,
  recentProjects,
  activeProjectId,
}: HomeShowcaseProps) {
  const isInteractive = mode === "interactive";
  const recentState = recentReveal?.revealState ?? "visible";
  const discoverState = discoverReveal?.revealState ?? "visible";
  const productFilmRef = useRef<HTMLDivElement>(null);
  const [productFilmLoaded, setProductFilmLoaded] = useState(false);

  useEffect(() => {
    if (!isInteractive || !hasIntroVideo || !productVideoUrl) {
      setProductFilmLoaded(false);
      return undefined;
    }

    const prefersReducedMotion = typeof window !== "undefined"
      && typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
      setProductFilmLoaded(true);
      return undefined;
    }

    const film = productFilmRef.current;
    if (!film) return undefined;

    if (typeof IntersectionObserver === "undefined") {
      setProductFilmLoaded(true);
      return undefined;
    }

    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      setProductFilmLoaded(true);
      observer.disconnect();
    }, { rootMargin: "200px" });
    observer.observe(film);
    return () => observer.disconnect();
  }, [hasIntroVideo, isInteractive, productVideoUrl]);

  return (
    <div className={`home home--${mode}`}>
      <section
        className={`hero ${isInteractive ? "is-motion-enabled" : ""} ${heroMotionReady ? "is-motion-ready" : ""}`}
        aria-labelledby="home-product-title"
      >
        <div className="hero__content">
          <HeroTitle />
          <p className="hero__body" data-home-typography-region="heroBody">
            AdCraft — The first agentic video production platform for marketing and advertising. Infinite canvas · shot-by-shot replication · fully automated, from idea to final cut.
          </p>
          <div className="hero__stage">
            {isInteractive && interactions ? (
              <button className="hero__create" type="button" onClick={interactions.createProject} data-home-typography-region="heroAction">
                <CreateProjectButtonContent />
              </button>
            ) : (
              <span className="hero__create hero__create--static" data-home-typography-region="heroAction">
                <CreateProjectButtonContent />
              </span>
            )}
          </div>
        </div>

        <div
          ref={productFilmRef}
          className="hero__film"
          aria-label="AdCraft product introduction media"
          data-media-slot="product-introduction"
          data-video-loaded={productFilmLoaded ? "true" : "false"}
        >
          {isInteractive && hasIntroVideo && productVideoUrl && productFilmLoaded ? (
            <video
              src={productVideoUrl}
              autoPlay
              loop
              muted
              playsInline
              preload="metadata"
              poster={homeProductPoster}
              onError={onProductVideoError}
            />
          ) : (
            <img src={homeProductPoster} alt="" />
          )}
        </div>
      </section>

      <div className="content-wrap">
        <section
          ref={recentReveal?.sectionRef}
          className="home-reveal home-reveal--recent"
          data-reveal-state={recentState}
          aria-label="Recent Projects"
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title="Recent Projects" subtitle="Pick up the latest creative thread." />
          </div>
          {isInteractive && interactions ? (
            <InteractiveRecentCards
              openWorkflow={interactions.openWorkflow}
              openProject={interactions.openProject}
              recentProjects={recentProjects ?? []}
              activeProjectId={activeProjectId ?? null}
            />
          ) : (
            <StaticRecentCards />
          )}
        </section>

        <section
          ref={discoverReveal?.sectionRef}
          className="home-reveal home-reveal--discover"
          data-reveal-state={discoverState}
          aria-label="Discover"
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title="Discover" subtitle="References, templates, and generated video ideas." />
          </div>
          {isInteractive && interactions ? <InteractiveDiscover openPreview={interactions.openPreview} /> : <StaticDiscover />}
        </section>
      </div>

      {isInteractive && interactions ? (
        <div className={`video-modal ${previewOpen ? "is-open" : ""}`}>
          <div className="modal-card">
            <div className="modal-preview"><span aria-hidden="true">▶</span></div>
            <div className="composer-footer" style={{ marginTop: 14 }}>
              <strong>Preview Case</strong>
              <button className="small-action" type="button" onClick={interactions.closePreview}>Close</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
