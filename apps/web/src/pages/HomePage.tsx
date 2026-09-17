import { useEffect, useState } from "react";
import { useHealth } from "../app/useHealth";
import { v2Api } from "../api/v2Client";
import type { ProjectV2Summary } from "../types-v2";
import type { RouteName } from "../types";
import { HomeShowcase } from "./HomeShowcase";
import { useHomeHeroMotionReady } from "./useHomeHeroMotionReady";
import { useHomeSectionReveal } from "./useHomeSectionReveal";
import "./home.css";

const homeProductVideoUrl = import.meta.env.VITE_HOME_PRODUCT_VIDEO_URL?.trim()
  || "/assets/home-product-film.mp4";

export function HomePage({ navigate }: { navigate: (route: RouteName, options?: { state?: unknown; projectId?: string }) => void }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [introVideoFailed, setIntroVideoFailed] = useState(false);
  const [recentProjects, setRecentProjects] = useState<ProjectV2Summary[]>([]);
  const isHeroMotionReady = useHomeHeroMotionReady();
  const recentReveal = useHomeSectionReveal();
  const discoverReveal = useHomeSectionReveal({ replay: true });
  const { startNewProject } = useHealth();
  const hasIntroVideo = Boolean(homeProductVideoUrl) && !introVideoFailed;

  useEffect(() => {
    let cancelled = false;
    async function loadProjects() {
      try {
        const response = await v2Api.listProjects("active", 10, null);
        if (cancelled) return;
        const sorted = [...response.items]
          .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
        setRecentProjects(sorted);
      } catch {
        // Home page stays usable with an empty recent-projects list if the API is unavailable.
      }
    }
    void loadProjects();
    return () => {
      cancelled = true;
    };
  }, []);

  async function createProject() {
    await startNewProject();
    navigate("workflow", { state: { startNewProject: true } });
  }

  return (
    <HomeShowcase
      mode="interactive"
      heroMotionReady={isHeroMotionReady}
      recentReveal={recentReveal}
      discoverReveal={discoverReveal}
      hasIntroVideo={hasIntroVideo}
      productVideoUrl={homeProductVideoUrl}
      onProductVideoError={() => setIntroVideoFailed(true)}
      previewOpen={modalOpen}
      interactions={{
        createProject: () => void createProject(),
        openWorkflow: () => navigate("workflow"),
        openProject: (projectId: string, _workflowId: string) => {
          navigate("workflow", { projectId });
        },
        openPreview: () => setModalOpen(true),
        closePreview: () => setModalOpen(false),
      }}
      recentProjects={recentProjects}
      activeProjectId={null}
    />
  );
}
