/** Decorative pixel art with explicit native proportions. */
import { buildingSprite, type PlaceKey } from './buildings';

function Sprite({ sprite, scale = 2, alt = '', className }: { sprite: { url: string; w: number; h: number }; scale?: number; alt?: string; className?: string }) {
  return <img className={`pixel ${className ?? ''}`} src={sprite.url} width={sprite.w * scale} height={sprite.h * scale} alt={alt} draggable={false} />;
}

export const Building = ({ place, scale = 2, alt = '' }: { place: PlaceKey; scale?: number; alt?: string }) => <Sprite sprite={buildingSprite(place)} scale={scale} alt={alt} />;

/**
 * public/assets/rooms has a header scene for twelve places. The Arsenal, which came later and has none of its own,
 * shows the scene of the Forge, the place of tools: a place listed here never asks for an image that does not exist.
 */
const SHARED_SCENE: Partial<Record<PlaceKey, PlaceKey>> = { arsenal: 'forge' };

export function SceneArt({ place }: { place: PlaceKey }) {
  return (
    <img
      key={place}
      className="pixel scene-image"
      src={`./assets/rooms/${SHARED_SCENE[place] ?? place}.webp`}
      width={768}
      height={192}
      alt=""
      decoding="async"
      draggable={false}
    />
  );
}
