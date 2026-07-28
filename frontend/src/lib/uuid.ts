export function newClientMutationId(): string {
  return crypto.randomUUID();
}
