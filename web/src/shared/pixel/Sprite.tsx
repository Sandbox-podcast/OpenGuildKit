/** Decorative pixel art with explicit native proportions. */
import { buildingSprite, type PlaceKey } from './buildings';

function Sprite({ sprite, scale = 2, alt = '', className }: { sprite: { url: string; w: number; h: number }; scale?: number; alt?: string; className?: string }) {
  return <img className={`pixel ${className ?? ''}`} src={sprite.url} width={sprite.w * scale} height={sprite.h * scale} alt={alt} draggable={false} />;
}

export const Building = ({ place, scale = 2, alt = '' }: { place: PlaceKey; scale?: number; alt?: string }) => <Sprite sprite={buildingSprite(place)} scale={scale} alt={alt} />;

export function SceneArt({ place }: { place: PlaceKey }) {
  return (
    <img
      key={place}
      className="pixel scene-image"
      src={`./assets/rooms/${place}.webp`}
      width={768}
      height={192}
      alt=""
      decoding="async"
      draggable={false}
    />
  );
}
