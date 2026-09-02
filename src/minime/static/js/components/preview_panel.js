export const PREVIEW_STATES = ["BUILDING", "PROBING", "READY", "FAILED", "STOPPED"];
export const previewIsStale = (preview, candidate) => Boolean(preview && candidate && (preview.head_sha !== candidate.candidate_sha || preview.base_sha !== candidate.base_sha || preview.image_digest !== candidate.image_digest));
export const previewBinding = (preview) => ({ head_sha: preview?.head_sha, base_sha: preview?.base_sha, image_digest: preview?.image_digest });
