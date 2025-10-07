"""
Optimized timeline service for production events.
Fixes N+1 query problems and implements proper Django ORM patterns.
"""
import logging
from typing import List, Dict, Any, Union
from django.db.models import Prefetch, Q
from django.utils.html import escape
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class TimelineService:
    """
    Service for retrieving and formatting production timeline data.
    Implements proper database optimization and security practices.
    """
    
    @staticmethod
    def get_production_timeline(production, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get optimized timeline data for a production with proper database queries.
        
        Args:
            production: History model instance
            limit: Maximum number of events to return
            
        Returns:
            List of formatted event dictionaries
        """
        try:
            # Import models locally to avoid circular imports
            from history.models import ChemicalEvent, EquipmentEvent, ProductionEvent
            from common.models import Gallery, GalleryImage
            
            # Optimized query with proper prefetch_related and select_related
            chemical_events = ChemicalEvent.objects.filter(
                history=production
            ).select_related(
                'history', 'history__product', 'album'
            ).prefetch_related(
                Prefetch('album__images', queryset=GalleryImage.objects.all())
            ).order_by('-date')[:limit]
            
            chemical_count = chemical_events.count()
            logger.info(f"DEBUG: Found {chemical_count} chemical events for production {production.id}")
            
            production_events = ProductionEvent.objects.filter(
                history=production
            ).select_related(
                'history', 'history__product', 'album'
            ).prefetch_related(
                Prefetch('album__images', queryset=GalleryImage.objects.all())
            ).order_by('-date')[:limit]
            
            production_count = production_events.count()
            logger.info(f"DEBUG: Found {production_count} production events for production {production.id}")
            
            equipment_events = EquipmentEvent.objects.filter(
                history=production
            ).select_related(
                'history', 'history__product', 'album'
            ).prefetch_related(
                Prefetch('album__images', queryset=GalleryImage.objects.all())
            ).order_by('-date')[:limit]
            
            equipment_count = equipment_events.count()
            logger.info(f"DEBUG: Found {equipment_count} equipment events for production {production.id}")
            
            total_events = chemical_count + production_count + equipment_count
            logger.info(f"DEBUG: Total events before processing: {total_events}")
            
            # Combine and sort events efficiently
            all_events = []
            
            # Process each event type
            for event in chemical_events:
                event_data = TimelineService._format_chemical_event(event)
                all_events.append((TimelineService._get_event_date(event), event_data))
            
            for event in production_events:
                event_data = TimelineService._format_production_event(event)
                all_events.append((TimelineService._get_event_date(event), event_data))
            
            for event in equipment_events:
                event_data = TimelineService._format_equipment_event(event)
                all_events.append((TimelineService._get_event_date(event), event_data))
            
            # Sort by date (newest first) and return only the data
            all_events.sort(key=lambda x: x[0], reverse=True)
            return [event_data for _, event_data in all_events[:limit]]
            
        except Exception as e:
            logger.error(f"Timeline service error for production {production.id}: {e}")
            return []
    
    @staticmethod
    def _get_event_date(event) -> Any:
        """Get standardized date from any event type."""
        return getattr(event, 'date', None)
    
    @staticmethod
    def _format_chemical_event(event) -> Dict[str, Any]:
        """Format ChemicalEvent with proper security and validation."""
        # Determine chemical type safely
        event_type = "chemical.application"  # Default
        commercial_name = str(getattr(event, "commercial_name", "") or getattr(event, "name", ""))
        
        if commercial_name:
            name_lower = commercial_name.lower()
            if "pesticide" in name_lower:
                event_type = "chemical.pesticide"
            elif any(term in name_lower for term in ["fertilizer", "fertiliser", "npk", "avocado-tone"]):
                event_type = "chemical.fertilizer"
            elif "herbicide" in name_lower:
                event_type = "chemical.herbicide"
        
        # Safe field access with validation
        try:
            # Volume field already contains formatted value with units (e.g., "50000 kg")
            volume_raw = getattr(event, "volume", "")
            volume_formatted = str(volume_raw) if volume_raw else ""
            
            # Area formatting
            area = TimelineService._safe_get_numeric(event, "area")
            area_formatted = TimelineService._format_area(area)
            
            event_data = {
                "id": f"chemical_{event.id}",
                "type": event_type,
                "date": TimelineService._get_event_date(event).isoformat(),
                "description": escape(getattr(event, "description", "") or ""),
                "observation": escape(getattr(event, "observation", "") or ""),
                "certified": bool(getattr(event, "certified", False)),
                
                # Chemical-specific fields
                "commercial_name": escape(commercial_name),
                "chemical_name": escape(getattr(event, "chemical_name", "") or ""),
                "volume": volume_formatted,
                "area": area_formatted,
                "volume_unit": escape(getattr(event, "volume_unit", "") or ""),
                "area_unit": escape(getattr(event, "area_unit", "") or ""),
                "npk_n_percentage": TimelineService._safe_get_numeric(event, "npk_n_percentage"),
                "npk_p_percentage": TimelineService._safe_get_numeric(event, "npk_p_percentage"),
                "npk_k_percentage": TimelineService._safe_get_numeric(event, "npk_k_percentage"),
                
                # Transparency fields for consumer understanding
                "weather_conditions": escape(getattr(event, "weather_conditions", "") or ""),
                "application_timing": escape(getattr(event, "time_period", "") or ""),
                "target_pest_disease": escape(getattr(event, "target_pest_disease", "") or ""),
                "application_method": escape(getattr(event, "way_of_application", "") or ""),
                "active_ingredient": escape(getattr(event, "commercial_name", "") or ""),
                "npk_ratio": TimelineService._get_npk_ratio_static(event),
            }
            
            # Add album data if available (already prefetched)
            album = getattr(event, 'album', None)
            if album:
                images = album.images.all()  # This won't hit the database due to prefetch
                if images:
                    event_data["albums"] = [
                        TimelineService._format_album_image(image) for image in images
                    ]
            
            return event_data
            
        except ValidationError as e:
            logger.warning(f"Validation error formatting chemical event {event.id}: {e}")
            return TimelineService._create_error_event(event, "chemical.application")
    
    @staticmethod
    def _format_production_event(event) -> Dict[str, Any]:
        """Format ProductionEvent with transparency fields following chemical event standards."""
        try:
            # Map database type codes to consumer-friendly event types
            event_type = "production.general"
            type_code = getattr(event, "type", "").upper()
            # Use name field or description as operation type fallback
            operation_type = str(getattr(event, "name", "") or getattr(event, "description", "")).lower()
            
            # Map specific type codes to consumer descriptions
            if type_code == "PL":
                event_type = "production.planting"
            elif type_code == "HA":
                event_type = "production.harvesting"
            elif type_code == "IR":
                event_type = "production.irrigation"
            elif type_code == "PR":
                event_type = "production.pruning"
            elif "harvest" in operation_type:
                event_type = "production.harvesting"
            elif "irrigation" in operation_type:
                event_type = "production.irrigation"
            elif operation_type:
                event_type = "production.operation"
            
            # Format transparency fields with units (following chemical event pattern)
            area_covered = TimelineService._safe_get_numeric(event, "area_covered")
            area_unit = getattr(event, "area_unit", "") or "ha"
            area_formatted = f"{area_covered} {area_unit}" if area_covered else ""
            
            yield_quantity = TimelineService._safe_get_numeric(event, "yield_quantity")
            yield_unit = getattr(event, "yield_unit", "") or "kg"
            yield_formatted = f"{yield_quantity} {yield_unit}" if yield_quantity else ""
            
            fuel_consumed = TimelineService._safe_get_numeric(event, "fuel_consumed")
            fuel_unit = getattr(event, "fuel_unit", "") or "L"
            fuel_formatted = f"{fuel_consumed} {fuel_unit}" if fuel_consumed else ""
            
            equipment_hours = TimelineService._safe_get_numeric(event, "equipment_hours")
            equipment_hours_formatted = f"{equipment_hours} hours" if equipment_hours else ""
            
            event_data = {
                "id": f"production_{event.id}",
                "type": event_type,
                "date": TimelineService._get_event_date(event).isoformat(),
                "description": escape(getattr(event, "notes", "") or getattr(event, "description", "") or ""),
                "observation": escape(getattr(event, "observation", "") or ""),
                "certified": bool(getattr(event, "certified", False)),
                "operation_type": escape(operation_type),
                
                # Transparency fields following chemical event standards
                "area_covered": area_formatted,
                "area_unit": escape(area_unit),
                "yield_quantity": yield_formatted,
                "yield_unit": escape(yield_unit),
                "fuel_consumed": fuel_formatted,
                "fuel_unit": escape(fuel_unit),
                "equipment_hours": equipment_hours_formatted,
                
                # Raw numeric values for calculations (matching chemical pattern)
                "area_covered_numeric": area_covered,
                "yield_quantity_numeric": yield_quantity,
                "fuel_consumed_numeric": fuel_consumed,
                "equipment_hours_numeric": equipment_hours,
                
                # Production-specific transparency fields
                "production_type": type_code,
                "production_name": escape(getattr(event, "name", "") or ""),
            }
            
            # Add album data if available
            album = getattr(event, 'album', None)
            if album:
                images = album.images.all()
                if images:
                    event_data["albums"] = [
                        TimelineService._format_album_image(image) for image in images
                    ]
            
            return event_data
            
        except Exception as e:
            logger.warning(f"Error formatting production event {event.id}: {e}")
            return TimelineService._create_error_event(event, "production.general")
    
    @staticmethod
    def _format_equipment_event(event) -> Dict[str, Any]:
        """Format EquipmentEvent with proper security."""
        try:
            event_data = {
                "id": f"equipment_{event.id}",
                "type": "production.equipment",
                "date": TimelineService._get_event_date(event).isoformat(),
                "description": escape(getattr(event, "notes", "") or getattr(event, "description", "") or ""),
                "observation": escape(getattr(event, "observation", "") or ""),
                "certified": bool(getattr(event, "certified", False)),
                "equipment_type": escape(getattr(event, "equipment_type", "") or ""),
            }
            
            # Add equipment details if available (already select_related)
            equipment = getattr(event, 'equipment', None)
            if equipment:
                event_data["equipment_name"] = escape(getattr(equipment, 'name', '') or '')
            
            # Add album data if available
            album = getattr(event, 'album', None)
            if album:
                images = album.images.all()
                if images:
                    event_data["albums"] = [
                        TimelineService._format_album_image(image) for image in images
                    ]
            
            return event_data
            
        except Exception as e:
            logger.warning(f"Error formatting equipment event {event.id}: {e}")
            return TimelineService._create_error_event(event, "production.equipment")
    
    @staticmethod
    def _format_album_image(image) -> Dict[str, str]:
        """Format gallery image data with proper URL generation."""
        try:
            return {
                "id": image.id,
                "title": escape(getattr(image, 'title', '') or f'Image {image.id}'),  # Use default title since GalleryImage has no title field
                "image_url": getattr(image, 'image_url', '') or getattr(image, 'url', ''),  # Use image_url field from GalleryImage model
            }
        except Exception as e:
            logger.warning(f"Error formatting gallery image {image.id}: {e}")
            return {"id": image.id, "title": f"Image {image.id}", "image_url": ""}
    
    @staticmethod
    def _safe_get_numeric(obj, field_name: str) -> Union[float, int, None]:
        """Safely get numeric field with validation."""
        try:
            from decimal import Decimal
            value = getattr(obj, field_name, None)
            if value is not None:
                # Handle Decimal, int, float, and string types
                return float(value) if isinstance(value, (int, float, str, Decimal)) else None
            return None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _get_npk_ratio_static(event) -> str:
        """Get NPK ratio in user-friendly format like '10-10-10'."""
        try:
            # Try individual percentage fields first (matching ChemicalEvent model)
            n = TimelineService._safe_get_numeric(event, "nitrogen_percentage")
            p = TimelineService._safe_get_numeric(event, "phosphorus_percentage")
            k = TimelineService._safe_get_numeric(event, "potassium_percentage")
            
            if n is not None and p is not None and k is not None:
                return f"{int(n)}-{int(p)}-{int(k)}"
                
            # Fallback to NPK fields (if from different source)
            n = TimelineService._safe_get_numeric(event, "npk_n_percentage")
            p = TimelineService._safe_get_numeric(event, "npk_p_percentage") 
            k = TimelineService._safe_get_numeric(event, "npk_k_percentage")
            
            if n is not None and p is not None and k is not None:
                return f"{int(n)}-{int(p)}-{int(k)}"
                
            # Fallback to concentration field
            concentration = getattr(event, "concentration", None)
            if concentration and "-" in str(concentration):
                return str(concentration)
                
            return ""
        except Exception:
            return ""
    
    @staticmethod
    def _format_volume(volume: Union[float, int, None]) -> str:
        """Format volume with appropriate units for legacy data compatibility."""
        if not volume:
            return ""
        
        # If it's a raw number, add default units
        if isinstance(volume, (int, float)):
            return f"{volume} kg"
        
        # If it's already a string with units, return as-is
        volume_str = str(volume)
        if any(unit in volume_str.lower() for unit in ['kg', 'g', 'lb', 'ton', 'liter', 'ml']):
            return volume_str
        
        # Add default units for raw numbers
        try:
            num_value = float(volume_str)
            return f"{num_value} kg"
        except ValueError:
            return volume_str
    
    @staticmethod
    def _format_area(area: Union[float, int, None]) -> str:
        """Format area with appropriate units for legacy data compatibility."""
        if not area:
            return ""
        
        # If it's a raw number, add default units
        if isinstance(area, (int, float)):
            return f"{area} hectares"
        
        # If it's already a string with units, return as-is
        area_str = str(area)
        if any(unit in area_str.lower() for unit in ['hectare', 'acre', 'ha', 'm²', 'sq']):
            return area_str
        
        # Add default units for raw numbers
        try:
            num_value = float(area_str)
            return f"{num_value} hectares"
        except ValueError:
            return area_str
    
    @staticmethod
    def _create_error_event(event, event_type: str) -> Dict[str, Any]:
        """Create minimal event data when formatting fails."""
        return {
            "id": f"error_{event.id}",
            "type": event_type,
            "date": TimelineService._get_event_date(event).isoformat() if TimelineService._get_event_date(event) else "",
            "description": "Event data temporarily unavailable",
            "observation": "",
            "certified": False,
        }