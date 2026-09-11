import { describe, expect, it } from 'vitest'
import { chunkBoundaries } from '../composables/useComposer'

describe('composer chunk boundaries', () => {
  it('does not split a message that fits', () => {
    expect(chunkBoundaries('short', 20)).toEqual([])
  })

  it('prefers a newline, then a space', () => {
    expect(chunkBoundaries('abc\ndefgh', 6)).toEqual([3])
    expect(chunkBoundaries('abcde fghij', 8)).toEqual([5])
  })

  it('hard cuts an unbroken message', () => {
    expect(chunkBoundaries('abcdefghij', 4)).toEqual([4, 8])
  })
})
