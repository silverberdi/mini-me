import { renderPipelineStepper } from "../components/pipeline_stepper.js";
import { renderAuditEvidence, renderCandidateEvidence, renderChecksEvidence, renderReviewEvidence, renderRunOverview } from "../views/evidence_views.js";
import { renderGitHubEvidence, renderTimelineEvidence } from "../views/github_timeline_views.js";
import { renderPreviewView } from "../views/preview_view.js";

/** Owns candidate-bound Run/Job detail projection into the existing drawer DOM. */
export function createDetailViewController({
  elements,
  previewActions,
  telemetryController,
  actionController,
  escapeHtml,
  sanitizeUrl,
  formatRelativeTime,
  formatTimestamp,
  statusClass,
}) {
  function render(detail) {
    if (!detail) return;
    elements.placeholder.style.display = "none";
    elements.content.style.display = "block";

    elements.changeName.textContent = detail.change_name;
    elements.status.textContent = detail.status;
    elements.status.className = `badge ${statusClass(detail.status)}`;
    elements.project.textContent = detail.project_id;
    const bindingState = detail.repository_binding_state || "UNKNOWN";
    elements.repository.textContent = bindingState === "VALID"
      ? (detail.repository_identity || "UNKNOWN")
      : bindingState === "INVALID" ? "Vínculo inválido" : "UNKNOWN";
    elements.repository.dataset.state = bindingState;
    elements.stage.textContent = detail.current_stage || "---";
    if (elements.stageLabel) elements.stageLabel.textContent = detail.stop_outcome === "CANCELLED" ? "Última etapa:" : "Etapa:";

    elements.generation.textContent = detail.candidate_authority
      ? `gen-${detail.candidate_authority.generation}` : "---";
    if (detail.candidate_authority?.candidate_sha) {
      elements.candidateSha.textContent = detail.candidate_authority.candidate_sha_short;
      elements.candidateSha.setAttribute("data-full-sha", detail.candidate_authority.candidate_sha);
      elements.copyShaButton.style.display = "inline-block";
    } else {
      elements.candidateSha.textContent = "---";
      elements.copyShaButton.style.display = "none";
    }

    renderPipelineStepper(elements.pipeline, detail.pipeline, { stopOutcome: detail.stop_outcome });
    renderRunOverview({
      metaGrid: elements.overviewMeta,
      blockerSection: elements.blockerSection,
      blockersList: elements.blockers,
      mobileState: elements.mobileRunState,
      mobileAttention: elements.mobileRunAttention,
      detail,
    });
    renderCandidateEvidence({ summary: elements.candidate, history: elements.candidateHistory, detail });
    renderChecksEvidence({ count: elements.checkCount, container: elements.checks, checks: detail.checks });
    renderReviewEvidence({ container: elements.review, review: detail.review, candidate: detail.candidate_authority });
    renderAuditEvidence({ container: elements.audit, audit: detail.audit, candidate: detail.candidate_authority });
    renderPreviewView({
      previewVal: detail.preview_validation,
      detail,
      elements: {
        status: elements.previewStatus,
        scenarios: elements.previewScenarios,
        history: elements.validationHistory,
        launchButton: elements.launchPreviewButton,
        teardownButton: elements.teardownPreviewButton,
      },
      previewActions,
      sanitizeUrl,
      formatRelativeTime,
    });
    renderGitHubEvidence(elements.github, detail.github, sanitizeUrl);
    void telemetryController.renderFor(detail);
    renderTimelineEvidence(elements.timeline, detail.timeline, formatTimestamp);
    void actionController.renderToolbar(detail);
  }

  return { render };
}
