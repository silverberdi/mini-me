export const candidateAuthorityLabel = (candidate) => candidate?.is_superseded ? "SUPERSEDED" : candidate?.is_frozen ? "FROZEN" : "CURRENT";
export const evidenceBindingStatus = (candidate, evidence) => !candidate || !evidence || candidate.candidate_sha !== evidence.candidate_sha ? "STALE" : "CURRENT";
