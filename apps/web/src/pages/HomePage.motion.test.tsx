import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/pages/home.css"), "utf8");
const homeSource = readFileSync(
  resolve(process.cwd(), "src/pages/HomePage.tsx"),
  "utf8",
);
const originalFontsDescriptor = Object.getOwnPropertyDescriptor(document, "fonts");

vi.mock("../app/useHealth", () => ({
  useHealth: () => ({ startNewProject }),
}));

vi.mock("../api/v2Client", () => ({
  v2Api: {
    listProjects: vi.fn().mockResolvedValue({
      items: [
        { project_id: "test-project-1", workflow_id: "test-workflow-1", name: "Test Project One", is_favorite: false, updated_at: new Date(Date.now() - 86400000).toISOString() },
        { project_id: "test-project-2", workflow_id: "test-workflow-2", name: "Test Project Two", is_favorite: true, updated_at: new Date(Date.now() - 172800000).toISOString() },
        { project_id: "test-project-3", workflow_id: "test-workflow-3", name: "Test Project Three", is_favorite: false, updated_at: new Date(Date.now() - 259200000).toISOString() },
      ],
    }),
  },
}));

type IntersectionCallback = IntersectionObserverCallback;

class IntersectionObserverMock {
  static instances: IntersectionObserverMock[] = [];

  readonly callback: IntersectionCallback;
  observedTarget: Element | null = null;
  readonly observe = vi.fn((target: Element) => {
    this.observedTarget = target;
  });
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
  readonly takeRecords = vi.fn(() => []);
  readonly root = null;
  readonly rootMargin = "0px";
  readonly thresholds = [0];

  constructor(callback: IntersectionCallback) {
    this.callback = callback;
    IntersectionObserverMock.instances.push(this);
  }

  setIntersection(
    target: Element,
    { isIntersecting, ratio }: { isIntersecting: boolean; ratio: number },
  ) {
    this.callback(
      [
        {
          boundingClientRect: target.getBoundingClientRect(),
          intersectionRatio: ratio,
          intersectionRect: target.getBoundingClientRect(),
          isIntersecting,
          rootBounds: null,
          target,
          time: 0,
        },
      ],
      this as unknown as IntersectionObserver,
    );
  }
}

describe("HomePage motion", () => {
  beforeEach(() => {
    startNewProject.mockReset();
    IntersectionObserverMock.instances = [];
    document.documentElement.removeAttribute("data-theme");
    vi.stubGlobal("IntersectionObserver", IntersectionObserverMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    if (originalFontsDescriptor) {
      Object.defineProperty(document, "fonts", originalFontsDescriptor);
    } else {
      Reflect.deleteProperty(document, "fonts");
    }
  });

  it("renders the title as three complete lines for the character reveal", () => {
    render(<HomePage navigate={vi.fn()} />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "One Sentence Becomes an Ad film.",
    });
    const lines = Array.from(
      title.querySelectorAll<HTMLElement>(".hero__line"),
    );

    expect(lines.slice(0, 2).map((line) => line.textContent?.replace(/\u00a0/g, " "))).toEqual([
      "ONE SENTENCE",
      "BECOMES AN",
    ]);

    expect(lines[2]?.getAttribute("data-accent-text")).toBe("Ad film.");
    expect(lines[2]?.getAttribute("data-home-hero-accent-reveal")).toBe("diagonal");
    expect(lines[2]?.querySelector("svg")).toBeNull();
    expect(title.querySelectorAll(".hero__character")).toHaveLength(0);
  });

  it("starts the hero motion only after fonts and two paint frames are ready", async () => {
    let resolveFonts: (() => void) | undefined;
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: {
        ready: new Promise<void>((resolve) => {
          resolveFonts = resolve;
        }),
      },
    });
    let heroPaintFrames = 0;
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      if (callback.name === "render") {
        return requestFrame.mock.calls.length;
      }
      heroPaintFrames += 1;
      callback(0);
      return requestFrame.mock.calls.length;
    });
    vi.stubGlobal("requestAnimationFrame", requestFrame);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());

    render(<HomePage navigate={vi.fn()} />);

    const hero = screen
      .getByRole("heading", {
        level: 1,
        name: "One Sentence Becomes an Ad film.",
      })
      .closest("section");
    expect(hero?.classList.contains("is-motion-ready")).toBe(false);

    await act(async () => {
      resolveFonts?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(heroPaintFrames).toBe(2);
    expect(hero?.classList.contains("is-motion-ready")).toBe(true);
  });

  it("reveals each content region once when it first enters the viewport", async () => {
    render(<HomePage navigate={vi.fn()} />);

    const recentSection = screen
      .getByRole("heading", { level: 2, name: "Recent Projects" })
      .closest("section");
    const discoverSection = screen
      .getByRole("heading", { level: 2, name: "Discover" })
      .closest("section");

    expect(recentSection).not.toBeNull();
    expect(discoverSection).not.toBeNull();
    expect(recentSection?.getAttribute("data-reveal-state")).toBe("pending");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(recentSection?.querySelectorAll(".recent[data-reveal-item]")).toHaveLength(4);
    // 首页共 4 个观察者：产品影片懒加载 + recent 揭示 + discover 揭示 +
    // DiscoverOrbit 视口跟踪（此前 3 的断言停在 Orbit 观察者加入之前）
    expect(IntersectionObserverMock.instances).toHaveLength(4);

    const recentObserver = IntersectionObserverMock.instances.find(
      (observer) => observer.observedTarget === recentSection,
    );
    const discoverObserver = IntersectionObserverMock.instances.find(
      (observer) => observer.observedTarget === discoverSection,
    );
    act(() => recentObserver?.setIntersection(
      recentSection as Element,
      { isIntersecting: true, ratio: 0.4 },
    ));

    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");
    expect(recentObserver?.disconnect).toHaveBeenCalledOnce();

    act(() => recentObserver?.setIntersection(
      recentSection as Element,
      { isIntersecting: false, ratio: 0 },
    ));
    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
  });

  it("replays Discover after it fully leaves and re-enters the viewport", () => {
    render(<HomePage navigate={vi.fn()} />);

    const discoverSection = screen
      .getByRole("heading", { level: 2, name: "Discover" })
      .closest("section");
    const discoverObserver = IntersectionObserverMock.instances.find(
      (observer) => observer.observedTarget === discoverSection,
    );

    act(() => discoverObserver?.setIntersection(
      discoverSection as Element,
      { isIntersecting: true, ratio: 0.4 },
    ));
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("visible");

    act(() => discoverObserver?.setIntersection(
      discoverSection as Element,
      { isIntersecting: false, ratio: 0 },
    ));
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");

    act(() => discoverObserver?.setIntersection(
      discoverSection as Element,
      { isIntersecting: true, ratio: 0.4 },
    ));
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverObserver?.disconnect).not.toHaveBeenCalled();
  });

  it("shows content immediately when the user prefers reduced motion", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(prefers-reduced-motion: reduce)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );

    render(<HomePage navigate={vi.fn()} />);

    const recentSection = screen
      .getByRole("heading", { level: 2, name: "Recent Projects" })
      .closest("section");
    const discoverSection = screen
      .getByRole("heading", { level: 2, name: "Discover" })
      .closest("section");

    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("visible");
    // reduced motion 下**没有揭示观察者**（useHomeSectionReveal 直接置可见并
    // 跳过 observe）。非动画用途的观察者（影片懒加载 / Orbit 视口跟踪）仍允许
    // 存在——它们不是运动效果，懒加载不该被偏好设置关掉。
    expect(
      IntersectionObserverMock.instances.filter(
        (observer) =>
          observer.observedTarget === recentSection ||
          observer.observedTarget === discoverSection,
      ),
    ).toHaveLength(0);
  });

  it("queues title lines from opposite edges without collision effects", () => {
    expect(styles).toMatch(
      /\.hero__line\s*\{[^}]*filter:\s*none;[^}]*white-space:\s*nowrap;/s,
    );
    expect(styles).toMatch(
      /\.hero__body\s*\{[^}]*opacity:\s*1;/s,
    );
    expect(styles).toMatch(
      /\.hero__film\s*\{[^}]*opacity:\s*1;/s,
    );
    expect(styles).toMatch(
      /\.hero__glyph\s*\{[^}]*opacity:\s*1;[^}]*transform:\s*none;/s,
    );
    expect(styles).toMatch(
      /\.hero\.is-motion-ready\s+\.hero__line\[data-home-hero-queue-ready="true"\]\s+\.hero__glyph\s*\{[^}]*home-hero-character-queue-enter[^}]*calc\(var\(--home-hero-line-delay\) \+ var\(--home-hero-character-index\) \* var\(--home-hero-character-stagger\)\)/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-character-queue-enter\s*\{[\s\S]*?translateX\(var\(--home-hero-character-start-offset\)\)[\s\S]*?transform:\s*none;/,
    );
    expect(styles).not.toMatch(
      /home-hero-spotlight-focus/,
    );
    expect(styles).not.toContain("home-hero-character-queue-collide");
    expect(styles).not.toContain("home-hero-character-bump-target");
    expect(styles).not.toContain("home-hero-character-collision-offset");
    expect(styles).toMatch(
      /\.hero\s*\{[^}]*--home-hero-character-stagger:\s*250ms;[^}]*--home-hero-accent-start-delay:\s*3020ms;/s,
    );
    expect(styles).toMatch(
      /\.hero\.is-motion-enabled \.hero__body\s*\{[^}]*opacity:\s*0;[^}]*filter:\s*blur\(10px\);/s,
    );
    expect(styles).toMatch(
      /\.hero\.is-motion-ready \.hero__body\s*\{[^}]*home-hero-body-fade[^}]*var\(--home-hero-accent-start-delay\)/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-body-fade\s*\{[\s\S]*?opacity:\s*0;[\s\S]*?filter:\s*blur\(10px\);[\s\S]*?opacity:\s*1;[\s\S]*?filter:\s*blur\(0\);/,
    );
    expect(styles).not.toMatch(
      /\.hero\.is-motion-ready\s+\.hero__(stage|film)\s*\{/,
    );
    expect(styles).not.toContain("home-hero-support-in");
    expect(styles).not.toContain("home-hero-media-in");
    expect(styles).toMatch(
      /\.home-reveal\[data-reveal-state="pending"\][\s\S]*?opacity:\s*0;/,
    );
    expect(styles).toMatch(
      /\.home-reveal\[data-reveal-state="visible"\][\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.hero__char[\s\S]*?animation:\s*none !important;[\s\S]*?opacity:\s*1 !important;[\s\S]*?transform:\s*none !important;/,
    );
  });

  it("does not mount an animated cosmic layer over the shared static background", () => {
    const view = render(<HomePage navigate={vi.fn()} />);

    expect(
      view.container.querySelectorAll(".home-cosmic-scene"),
    ).toHaveLength(0);
    expect(homeSource).not.toContain("HomeCosmicScene");
    expect(homeSource).not.toContain("home-cosmic");
  });

  it("does not load a WebGL renderer for the static Home background", () => {
    expect(homeSource).not.toMatch(/from\s+["']three["']/);
    expect(homeSource).not.toContain("homeCosmicRenderer");
  });
});
